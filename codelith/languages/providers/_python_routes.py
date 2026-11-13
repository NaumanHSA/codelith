"""
What QA needs from Python to follow a request: who is let in, and where its data goes.

**Guards.** A route is guarded when something requires a signed-in caller before its
handler runs: a dependency in its signature (`Depends(get_current_user)`, a parameter
typed `CurrentUser`), a decorator (`@login_required`, `@jwt_required()`), its router's
`dependencies=[...]`, or a guard over the whole app (an auth middleware, a
`before_request` hook that checks a token). Names are matched, not types resolved: a
guard called `ensure_signed_in` is missed, and QA says the result is *likely*.

**Sinks.** A call that does something dangerous with a value — runs it as SQL or a
command, opens it as a path, fetches it as a URL, writes it to a log, unpickles it —
and whether that value comes from the function's own parameters, followed through
plain assignments inside the function. QA joins this with the recorded calls: a sink in
a function that a route's handler reaches, fed from its caller, is request data
reaching that sink.
"""

from __future__ import annotations

import ast
import re

from codelith.languages.base import FlowFacts, Guards, Sink
from codelith.languages.providers._python_entities import _dotted

#: Names that mean "the caller must be signed in": in a dependency, a decorator, a type.
AUTH = re.compile(
    r"(auth|login_required|current_?user|currentuser|get_current_\w+|admin|get_user|signed_in|require_?(user|admin|role|auth|login|scope|permission|token)"
    r"|permission|role|jwt|bearer|verify_?token|api_?key|is_authenticated|oauth2|token_required|admin_required|guard|protect)",
    re.IGNORECASE,
)

#: Parameters that are not input from the request: the session, the caller, settings.
_NOT_INPUT = re.compile(r"^(self|cls|db|session|conn|connection|user|current_user|settings|config|background_tasks|logger|log)$")

_SQL_CALLS = frozenset({"execute", "executemany", "exec_driver_sql", "executescript", "raw", "text"})
_SHELL_CALLS = {"os.system", "os.popen"}
_SUBPROCESS = frozenset({"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"})
#: Calls that open, send or delete the file at a path. Building a path is not one.
_FILE_CALLS = frozenset({"open", "io.open", "FileResponse", "send_file", "os.remove", "os.unlink", "shutil.rmtree", "shutil.copy", "shutil.move"})
_URL_CALLS = re.compile(r"^(requests|httpx|aiohttp|urllib\.request)\.(get|post|put|patch|delete|head|request|urlopen|stream)$|\.(get|post|put|patch|delete|request|stream)$")
_DESERIALISE = frozenset({"pickle.load", "pickle.loads", "dill.loads", "marshal.loads", "yaml.load", "yaml.unsafe_load", "jsonpickle.decode"})
#: A function doing one of these checks that a path stays inside the folder it meant.
_CONTAINED = re.compile(r"(is_relative_to\(|\bin\s+[\w.]+\.parents\b|commonpath\(|safe_join\(|secure_filename\(|realpath\([^)]*\)\.startswith|resolve\(\)\s*\.is_relative_to)")

_LOG = re.compile(r"(^|\.)(debug|info|warning|warn|error|exception|critical)$")
#: Parameter names that hold what the request sent, worth not logging whole.
_REQUEST_DATA = re.compile(r"^(request|req|body|payload|data|form|json|headers|params|query|item|form_data)$", re.IGNORECASE)


def _text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # an odd node is not worth failing a scan over
        return ""


def _signature_guard(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for dec in fn.decorator_list:
        text = _text(dec)
        # A route decorator's own `dependencies=[...]` guards it; its path does not.
        if isinstance(dec, ast.Call):
            for kw in dec.keywords:
                if kw.arg == "dependencies" and AUTH.search(_text(kw.value)):
                    return _text(kw.value)
            if AUTH.search(_dotted(dec.func)):
                return text
        elif AUTH.search(text):
            return text
    args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
    for arg in args:
        if arg.annotation is not None and AUTH.search(_text(arg.annotation)):
            return f"{arg.arg}: {_text(arg.annotation)}"
    for default in [*fn.args.defaults, *[d for d in fn.args.kw_defaults if d is not None]]:
        if "Depends" in _text(default) and AUTH.search(_text(default)):
            return _text(default)
    return None


def _inputs(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """The parameters that carry input: not the session, the caller, or a dependency."""
    out: set[str] = set()
    positional = [*fn.args.posonlyargs, *fn.args.args]
    defaults: dict[str, ast.expr] = {}
    if fn.args.defaults:
        defaults.update(zip([a.arg for a in positional[-len(fn.args.defaults) :]], fn.args.defaults, strict=False))
    for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=False):
        if d is not None:
            defaults[a.arg] = d
    for a in [*positional, *fn.args.kwonlyargs]:
        annotation = _text(a.annotation)
        if _NOT_INPUT.match(a.arg) or "Depends" in annotation or "Depends" in _text(defaults.get(a.arg)) or AUTH.search(annotation):
            continue
        if re.search(r"\b(Session|AsyncSession|Connection|Engine|Settings|BackgroundTasks)\b", annotation):
            continue
        out.add(a.arg)
    if fn.args.vararg:
        out.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        out.add(fn.args.kwarg.arg)
    return out


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _own(fn: ast.AST):
    """Every node of a function's body, not descending into functions defined inside it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _built_text(node: ast.AST | None) -> bool:
    """A string assembled at runtime: an f-string with fields, `+` or `%` with text, `.format`."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        sides = (node.left, node.right)
        text = any((isinstance(x, ast.Constant) and isinstance(x.value, str)) or _built_text(x) for x in sides)
        return text and not all(isinstance(x, ast.Constant) for x in sides)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return isinstance(node.func.value, ast.Constant)
    if isinstance(node, ast.Call) and _dotted(node.func).rsplit(".", 1)[-1] == "text" and node.args:
        return _built_text(node.args[0])
    return False


def _strings_built(fn: ast.AST) -> set[str]:
    """Names assigned a string built at runtime, inside the function."""
    out: set[str] = set()
    for n in _own(fn):
        if isinstance(n, ast.Assign) and _built_text(n.value):
            for t in n.targets:
                out |= _names(t)
    return out


def _tainted(fn: ast.FunctionDef | ast.AsyncFunctionDef, start: set[str]) -> set[str]:
    """Parameters, and the names assigned from them inside the function, in order."""
    tainted = set(start)
    assigns = sorted(
        (n for n in _own(fn) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and getattr(n, "value", None) is not None),
        key=lambda n: (n.lineno, n.col_offset),
    )
    for node in assigns:
        if _names(node.value) & tainted:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                tainted |= _names(t)
    return tainted


def _sink_kind(call: ast.Call) -> str | None:
    callee = _dotted(call.func)
    tail = callee.rsplit(".", 1)[-1]
    if tail in _SQL_CALLS:
        return "sql"
    if callee in _SHELL_CALLS or (callee.startswith("subprocess.") and tail in _SUBPROCESS):
        return "shell"
    if callee in ("eval", "exec"):
        return "code"
    if callee in _DESERIALISE:
        return "deserialize"
    if callee in _FILE_CALLS or tail in ("FileResponse", "send_file", "send_from_directory"):
        return "file"
    if _URL_CALLS.search(callee) and callee.split(".", 1)[0] in ("requests", "httpx", "aiohttp", "urllib", "client", "session", "http"):
        return "url"
    if _LOG.search(callee) and "log" in callee.lower():
        return "log"
    return None


def _first(call: ast.Call, kind: str) -> list[ast.AST]:
    """The arguments that decide what the call does with its input."""
    if kind in ("sql", "code", "deserialize", "url", "file"):
        picked = call.args[:1] or [k.value for k in call.keywords if k.arg in ("url", "path", "file", "filename", "statement", "sql", "query")]
        return list(picked)
    if kind == "shell":
        shell = any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords)
        if _dotted(call.func) in _SHELL_CALLS or shell:
            return list(call.args[:1])
        return []  # a list of arguments with no shell does not run a second command
    if kind == "log":
        return [*call.args, *[k.value for k in call.keywords]]
    return []


class _Walker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.guards = Guards()
        self.sinks: list[Sink] = []
        self.fields: list[tuple[str, str, int]] = []
        self.response_models: set[str] = set()
        self.models: dict[str, list[tuple[str, int]]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = {_dotted(b).rsplit(".", 1)[-1] for b in node.bases}
        fields: list[tuple[str, int]] = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields.append((item.target.id, item.lineno))
            # Django REST framework: a class that requires a signed-in caller.
            if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "permission_classes" for t in item.targets):
                text = _text(item.value)
                if "AllowAny" not in text and text.strip("[]() "):
                    self.guards.handlers[f"{'.'.join([*self.scope, node.name])}.*"] = f"permission_classes = {text}"
        if bases & {"BaseModel", "Schema", "SQLModel", "ModelSchema"} or any("Model" in b for b in bases):
            self.models[node.name] = fields
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qname = ".".join([*self.scope, node.name])
        if guard := _signature_guard(node):
            self.guards.handlers[qname] = guard
        else:
            names = sorted(
                {n for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs] if a.annotation is not None for n in _names(a.annotation)}
            )
            if names:
                self.guards.uses[qname] = names
        # A function that checks a path stays inside its folder is not a path traversal.
        contained = bool(_CONTAINED.search(_text(node)))
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "response_model":
                        self.response_models |= {n for n in _names(kw.value)}
            # An app-wide check: a `before_request` hook, or an HTTP middleware, that looks at credentials.
            text = _text(dec)
            if ("before_request" in text or "middleware" in text) and AUTH.search(_text(node)):
                self.guards.app = self.guards.app or f"{text} {node.name}"
        tainted = _tainted(node, _inputs(node))
        built = _strings_built(node)
        for sub in _own(node):
            if not isinstance(sub, ast.Call):
                continue
            kind = _sink_kind(sub)
            if kind is None:
                continue
            args = _first(sub, kind)
            # A query object (`select(...).where(x == value)`) passes values as
            # parameters: only SQL text assembled from values is a way in.
            if kind == "sql":
                args = [a for a in args if _built_text(a) or (isinstance(a, ast.Name) and a.id in built)]
            used = sorted(set().union(*(_names(a) for a in args)) & tainted) if args else []
            if kind == "log":
                # Logged whole (`body`, `{payload}`), not one field of it (`params["model"]`).
                bare = {a.id for a in args if isinstance(a, ast.Name)} | {
                    v.value.id
                    for a in args
                    if isinstance(a, ast.JoinedStr)
                    for v in a.values
                    if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)
                }
                used = [u for u in used if _REQUEST_DATA.match(u) and u in bare]
            if kind == "file" and contained:
                continue
            if used:
                self.sinks.append(Sink(kind, sub.lineno, qname, used, _dotted(sub.func) or "call"))
        self.scope.append(node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # AdminUser = Annotated[User, Depends(get_current_admin)]
        if not self.scope and isinstance(node.value, ast.Subscript) and _dotted(node.value.value).rsplit(".", 1)[-1] == "Annotated":
            text = _text(node.value)
            if "Depends" in text and AUTH.search(text.split("Depends", 1)[1]):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.guards.aliases[t.id] = text
        # router = APIRouter(dependencies=[Depends(require_user)])
        if isinstance(node.value, ast.Call) and _dotted(node.value.func).rsplit(".", 1)[-1] in ("APIRouter", "Blueprint", "Router"):
            for kw in node.value.keywords:
                if kw.arg == "dependencies" and AUTH.search(_text(kw.value)):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            self.guards.routers[t.id] = _text(kw.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # app.add_middleware(AuthMiddleware), app.include_router(r, dependencies=[...]) for the app
        callee = _dotted(node.func)
        if callee.endswith("add_middleware") and node.args and AUTH.search(_text(node.args[0])):
            self.guards.app = self.guards.app or f"add_middleware({_text(node.args[0])})"
        self.generic_visit(node)


def flow_facts(source: str) -> FlowFacts | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    walker = _Walker()
    walker.visit(tree)
    return FlowFacts(
        guards=walker.guards,
        sinks=walker.sinks,
        response_models=walker.response_models,
        models=walker.models,
    )


__all__ = ["AUTH", "flow_facts"]
