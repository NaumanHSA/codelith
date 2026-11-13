"""
What QA looks for in Python, on the syntax tree.

Each rule says what is wrong, why it matters and what to do, in words a reviewer would
use. They are tuned against real code to say nothing where nothing is wrong: an
`except Exception` that logs is handling an error, `hashlib.md5` for a cache key is not
a password hash, and `max_tokens` in a log line is a number, not a credential. A rule
that cannot tell is marked `likely`, never `confirmed`.

Test files get only the rules about tests: `eval` in a test is a test of `eval`.
"""

from __future__ import annotations

import ast
import re

from codelith.languages.base import Issue
from codelith.languages.providers._python_entities import _dotted

#: A call whose name has one of these in it is handling an error, not dropping it.
_HANDLING = re.compile(
    r"(log|warn|error|exception|critical|print|report|capture|sentry|notify|emit|record|abort|fail|echo)",
    re.IGNORECASE,
)

#: Names that hold credentials. `token` alone only as a whole word: an LLM codebase is
#: full of `max_tokens`, `token_count` and `prompt_tokens`, which are numbers.
_SECRET_NAME = re.compile(
    r"(^|_)(password|passwd|pwd|secret|api_?key|apikey|access_?token|refresh_?token|auth_?token|id_?token|"
    r"bearer|authorization|credentials?|private_?key|client_?secret|session_?token|csrf_?token|jwt)(_|$)"
    r"|^token$",
    re.IGNORECASE,
)

#: Names a value made by `random` should not have.
_SECURITY_NAME = re.compile(
    r"(token|secret|password|passwd|otp|nonce|salt|api_?key|session|csrf|reset_code|verification)",
    re.IGNORECASE,
)

_SQL = re.compile(r"\b(select|insert\s+into|update|delete\s+from|create\s+table|drop\s+table|alter\s+table)\b", re.IGNORECASE)

_DDL = re.compile(r"^\s*(create|alter|drop)\s+(table|index|column|view)\b", re.IGNORECASE)

_REQUESTS_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "request"})
_SUBPROCESS = frozenset({"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"})
_BLOCKING = {
    "time.sleep": "`time.sleep` stops every other request this process is serving",
    "urllib.request.urlopen": "`urlopen` waits on the network with the whole event loop held",
    "os.system": "`os.system` waits for the command with the whole event loop held",
}
_DESERIALISE = {
    "pickle.load": "pickle",
    "pickle.loads": "pickle",
    "cPickle.loads": "pickle",
    "dill.load": "dill",
    "dill.loads": "dill",
    "marshal.load": "marshal",
    "marshal.loads": "marshal",
    "jsonpickle.decode": "jsonpickle",
    "yaml.unsafe_load": "yaml.unsafe_load",
}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(_dotted(n).rsplit(".", 1)[-1] in ("Exception", "BaseException") for n in names)


def _handles(body: list[ast.stmt]) -> bool:
    """Whether an except body does anything with the error: raises, logs, reports, returns it."""
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name and _HANDLING.search(name):
                return True
        # Kept for later: `self.error = e`, `errors.append(e)`, `return {"error": ...}`.
        if isinstance(node, (ast.Return, ast.Yield)) and node.value is not None and not isinstance(node.value, ast.Constant):
            return True
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("append", "add", "put", "set_exception", "send"):
            return True
    return False


#: Calls that say something about a value without giving it away.
_SAFE_WRAPPERS = re.compile(r"^(bool|len|type|id|hash|isinstance|mask\w*|redact\w*|_?hash\w*|obfuscate\w*)$")


def _leaks(node: ast.AST) -> str | None:
    """
    A credential-looking name whose value would be written out: not one only tested
    (`api_key is not None`) or summarised (`bool(token)`, `len(password)`).
    """
    if isinstance(node, ast.Compare):
        return None
    if isinstance(node, ast.Call) and _SAFE_WRAPPERS.match(_dotted(node.func).rsplit(".", 1)[-1] or ""):
        return None
    name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
    if name and _SECRET_NAME.search(name):
        return name
    for child in ast.iter_child_nodes(node):
        if found := _leaks(child):
            return found
    return None


def _mentions(node: ast.AST, pattern: re.Pattern) -> str | None:
    """The first name or attribute under `node` that matches `pattern`."""
    for sub in ast.walk(node):
        name = sub.id if isinstance(sub, ast.Name) else sub.attr if isinstance(sub, ast.Attribute) else None
        if name and pattern.search(name):
            return name
    return None


def _is_text_built(node: ast.AST) -> bool:
    """A string assembled from values at runtime: an f-string with fields, `+`, `%`, `.format`."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        sides = (node.left, node.right)
        text = any(
            (isinstance(side, ast.Constant) and isinstance(side.value, str)) or isinstance(side, ast.JoinedStr) or _is_text_built(side)
            for side in sides
        )
        return text and not all(isinstance(side, ast.Constant) for side in sides)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return isinstance(node.func.value, ast.Constant) and bool(node.args or node.keywords)
    return False


def _text_of(node: ast.AST) -> str:
    """The literal text inside a built string, to see whether it is SQL."""
    return " ".join(
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_false(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _is_literal(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(isinstance(e, ast.Constant) for e in node.elts)
    return False


class _Inspector(ast.NodeVisitor):
    def __init__(self, is_test: bool, stem: str, lines: list[str]) -> None:
        self.is_test = is_test
        self.stem = stem
        self.lines = lines
        self.out: list[Issue] = []
        #: The enclosing functions, innermost last: (name, is_async).
        self.functions: list[tuple[str, bool]] = []
        #: The names bound by the except handlers we are inside.
        self.caught: list[str] = []
        #: The names bound by handlers that catch broadly: whose text could be anything.
        self.caught_broad: list[str] = []
        #: Per function: names assigned a built string that reads as SQL.
        self.sql_names: list[dict[str, int]] = [{}]

    def add(self, node: ast.AST, rule: str, area: str, severity: str, title: str, message: str, fix: str, confidence: str = "confirmed") -> None:
        self.out.append(
            Issue(
                rule=rule,
                area=area,
                severity=severity,
                line=getattr(node, "lineno", 1),
                end_line=getattr(node, "end_lineno", None),
                title=title,
                message=message,
                fix=fix,
                confidence=confidence,
            )
        )

    # -- scopes -------------------------------------------------------------------

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        if self.is_test:
            if node.name.startswith("test") and not self._asserts(node):
                self.add(
                    node,
                    "py.test-asserts-nothing",
                    "tests",
                    "low",
                    f"`{node.name}` asserts nothing",
                    "A test with no assertion passes as long as nothing raises, so it can stay green while the "
                    "behaviour it is named for breaks.",
                    "Assert on the result, or use `pytest.raises` for the error it should raise.",
                    "likely",
                )
        else:
            self._defaults(node)
        self.functions.append((node.name, is_async))
        self.sql_names.append({})
        self.generic_visit(node)
        self.sql_names.pop()
        self.functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, True)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # A lambda inside an async function runs whenever it is called, not in the coroutine.
        self.functions.append(("<lambda>", False))
        self.generic_visit(node)
        self.functions.pop()

    @staticmethod
    def _asserts(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assert):
                return True
            if isinstance(sub, ast.Call):
                name = _dotted(sub.func).lower()
                if any(w in name for w in ("assert", "raises", "expect", "verify", "check", "fail", "snapshot", "warns")):
                    return True
            if isinstance(sub, ast.With) and any("raises" in _dotted(getattr(i.context_expr, "func", i.context_expr)) for i in sub.items):
                return True
        return False

    def _defaults(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]:
            mutable = isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(default, ast.Call) and _dotted(default.func) in ("list", "dict", "set", "collections.defaultdict")
            )
            if mutable:
                self.add(
                    default,
                    "py.mutable-default",
                    "breaks",
                    "medium",
                    f"`{node.name}` has a mutable default argument",
                    "The default is made once, when the function is defined, and shared by every call: what one "
                    "call adds to it, the next call sees.",
                    "Default to `None` and create the list or dict inside the function.",
                )

    # -- errors ---------------------------------------------------------------------

    def _explained(self, handler: ast.ExceptHandler) -> bool:
        """A handler with a comment in it says why it drops the error: that is the rule's own advice."""
        end = handler.end_lineno or handler.lineno
        return any("#" in self.lines[i] for i in range(handler.lineno - 1, min(end, len(self.lines))))

    def visit_Try(self, node: ast.Try) -> None:
        if not self.is_test:
            for handler in node.handlers:
                if self._explained(handler):
                    continue
                if handler.type is None and not any(isinstance(n, ast.Raise) and n.exc is None for n in ast.walk(handler)):
                    self.add(
                        handler,
                        "py.bare-except",
                        "errors",
                        "medium",
                        "A bare `except:` catches everything, Ctrl+C included",
                        "`except:` also catches `KeyboardInterrupt` and `SystemExit`, so the program cannot be "
                        "stopped cleanly, and errors nobody expected disappear with the ones somebody did.",
                        "Catch the exceptions you expect, or `except Exception:` and log it.",
                    )
                elif _is_broad(handler) and not _handles(handler.body):
                    self.add(
                        handler,
                        "py.swallowed-exception",
                        "errors",
                        "medium",
                        "An exception is caught and dropped",
                        "Every error in the `try` block ends here with nothing logged or raised: when it goes "
                        "wrong in production, nothing says so, and the code carries on as if it had worked.",
                        "Log it (`logger.exception(...)`), re-raise it, or catch only the error you mean to ignore "
                        "and say why in a comment.",
                    )
        for handler in node.handlers:
            self.caught.append(handler.name or "")
            self.caught_broad.append((handler.name or "") if _is_broad(handler) else "")
            for stmt in handler.body:
                self.visit(stmt)
            self.caught_broad.pop()
            self.caught.pop()
        for part in (node.body, node.orelse, node.finalbody):
            for stmt in part:
                self.visit(stmt)

    visit_TryStar = visit_Try

    def visit_Raise(self, node: ast.Raise) -> None:
        bound = [c for c in self.caught if c]
        if (
            not self.is_test
            and bound
            and isinstance(node.exc, ast.Call)
            and node.cause is None
            # Turning an error into an HTTP response is the point, not a lost cause.
            and "http" not in _dotted(node.exc.func).lower()
            and _dotted(node.exc.func).rsplit(".", 1)[-1] not in ("abort", "Response", "JSONResponse")
            and not any(isinstance(n, ast.Name) and n.id in bound for n in ast.walk(node.exc))
        ):
            self.add(
                node,
                "py.raise-without-cause",
                "errors",
                "low",
                "A new error is raised in an `except` without `from`",
                "The traceback then reads as a second failure while handling the first, and the original "
                "error is not marked as the cause.",
                f"Raise it `from {bound[-1]}` to keep the cause, or `from None` if the original is noise.",
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if not self.is_test:
            for op, right in zip(node.ops, node.comparators, strict=False):
                if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(right, ast.Constant) and isinstance(right.value, (str, int, float, bytes)) and not isinstance(right.value, bool):
                    self.add(
                        node,
                        "py.is-literal",
                        "breaks",
                        "medium",
                        "`is` compared with a literal",
                        "`is` asks whether two names are the same object, not equal values. It happens to work "
                        "for some small numbers and short strings, and silently fails for others.",
                        "Use `==` or `!=`.",
                    )
        self.generic_visit(node)

    # -- assignments ----------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self.is_test:
            for target in node.targets:
                name = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else ""
                if name and _is_text_built(node.value) and _SQL.search(_text_of(node.value)):
                    self.sql_names[-1][name] = node.lineno
                if name and _SECURITY_NAME.search(name) and isinstance(node.value, ast.Call):
                    self._random(node.value, name)
                if (
                    name == "DEBUG"
                    and _is_true(node.value)
                    and not self.functions
                    and self.stem in ("settings", "config", "configuration", "conf", "app", "main")
                ):
                    self.add(
                        node,
                        "py.debug-on",
                        "security",
                        "medium",
                        "`DEBUG = True` in the settings",
                        "Debug mode shows tracebacks, settings and sometimes an interactive console to whoever "
                        "triggers an error.",
                        "Read it from the environment and default to off.",
                    )
                if name in ("check_hostname",) and _is_false(node.value):
                    self._tls(node, "Hostname checking is turned off")
                if name == "verify_mode" and _dotted(node.value).endswith("CERT_NONE"):
                    self._tls(node, "Certificate checking is turned off")
        self.generic_visit(node)

    def _random(self, call: ast.Call, name: str) -> None:
        callee = _dotted(call.func)
        if callee.startswith("random.") and callee.split(".", 1)[1] in (
            "random", "randint", "choice", "choices", "getrandbits", "randrange", "sample",
        ):
            self.add(
                call,
                "py.insecure-random",
                "security",
                "medium",
                f"`{name}` is made with `random`",
                "`random` is predictable: anyone who sees a few of its values can work out the next ones, so a "
                "token, password or code made with it can be guessed.",
                "Use `secrets.token_urlsafe()`, `secrets.token_hex()` or `secrets.choice()`.",
            )

    def _tls(self, node: ast.AST, title: str) -> None:
        self.add(
            node,
            "py.tls-off",
            "security",
            "high",
            title,
            "Without it, anyone between this code and the server can read and change the traffic, "
            "credentials included.",
            "Leave verification on; for a private certificate authority, pass its bundle (`verify=\"ca.pem\"`).",
        )

    # -- calls ----------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        if not self.is_test:
            self._call(node)
        self.generic_visit(node)

    def _call(self, node: ast.Call) -> None:
        callee = _dotted(node.func)
        tail = callee.rsplit(".", 1)[-1]
        first = node.args[0] if node.args else None
        in_async = bool(self.functions) and self.functions[-1][1]

        # Code and shell injection.
        if callee in ("eval", "exec") and first is not None and not isinstance(first, ast.Constant):
            self.add(
                node,
                "py.eval",
                "security",
                "high",
                f"`{callee}` runs a string it was handed",
                f"Whatever reaches this `{callee}` runs as Python with this process's permissions. If any part "
                "of the string can come from outside, so can the code.",
                "Parse the input instead (`ast.literal_eval` for literals, `json.loads` for data), or look the "
                "operation up in a dict of allowed ones.",
            )
        if callee.startswith("subprocess.") and tail in _SUBPROCESS and _is_true(_kw(node, "shell")) and first is not None and not _is_literal(first):
            self.add(
                node,
                "py.shell-injection",
                "security",
                "high",
                "A shell command is built from values",
                "With `shell=True`, a value containing `;`, `&&` or backticks runs a second command of its own.",
                "Pass the command as a list without `shell=True`: `subprocess.run([\"git\", \"log\", ref])`.",
            )
        if callee in ("os.system", "os.popen") and first is not None and not _is_literal(first):
            self.add(
                node,
                "py.shell-injection",
                "security",
                "high",
                f"`{callee}` runs a command built from values",
                "The command goes through the shell, so a value containing `;` or `&&` runs a command of its own.",
                "Use `subprocess.run` with the command as a list.",
            )

        # SQL built from values.
        if tail in ("execute", "executemany", "exec_driver_sql", "executescript", "raw", "text") and first is not None:
            built = _is_text_built(first) and bool(_SQL.search(_text_of(first)))
            named = isinstance(first, ast.Name) and first.id in self.sql_names[-1]
            ddl = built and bool(_DDL.search(_text_of(first)))
            if ddl:
                self.add(
                    node,
                    "py.sql-built",
                    "security",
                    "medium",
                    "A schema statement is built from values",
                    "Table and column names cannot be passed as parameters, so they are pasted in: fine when they "
                    "come from the code, an injection when any of them can come from a request.",
                    "Check each name against a fixed list (or a pattern like `^[a-z_]+$`) before it is pasted in.",
                    "likely",
                )
            elif built or named:
                self.add(
                    node,
                    "py.sql-built",
                    "security",
                    "high",
                    "SQL is built from values",
                    "A value that reaches this query as text becomes part of it: a quote in it ends the string "
                    "and what follows runs as SQL.",
                    "Pass the values as parameters: `execute(\"... WHERE id = ?\", (user_id,))`, or `text(\"... :id\")` "
                    "with `{\"id\": user_id}`.",
                    "confirmed" if built else "likely",
                )

        # Unsafe deserialisation.
        if callee in _DESERIALISE and first is not None and not isinstance(first, ast.Constant):
            self.add(
                node,
                "py.unsafe-deserialization",
                "security",
                "high",
                f"`{callee}` on data that may come from outside",
                f"Loading {_DESERIALISE[callee]} data can run code: a crafted file or payload executes when it is "
                "read.",
                "Use a data format that cannot carry code (JSON), or load only files this program wrote itself.",
                "likely",
            )
        if callee == "yaml.load":
            loader = _kw(node, "Loader") or (node.args[1] if len(node.args) > 1 else None)
            if loader is None or not _dotted(loader).rsplit(".", 1)[-1].startswith(("Safe", "CSafe")):
                self.add(
                    node,
                    "py.unsafe-deserialization",
                    "security",
                    "high",
                    "`yaml.load` without the safe loader",
                    "The full loader builds arbitrary Python objects from tags in the document, which can run code.",
                    "Use `yaml.safe_load(...)`.",
                )

        # TLS, JWT, CORS, debug, temp files.
        if _is_false(_kw(node, "verify")) and (tail in _REQUESTS_METHODS or callee.split(".", 1)[0] in ("requests", "httpx", "session", "client", "self")):
            self._tls(node, "Certificate checking is turned off")
        if callee.endswith("_create_unverified_context"):
            self._tls(node, "An unverified TLS context")
        if callee.endswith("jwt.decode"):
            options = _kw(node, "options")
            off = _is_false(_kw(node, "verify")) or (
                isinstance(options, ast.Dict)
                and any(
                    isinstance(k, ast.Constant) and k.value == "verify_signature" and _is_false(v)
                    for k, v in zip(options.keys, options.values, strict=False)
                )
            )
            if off:
                self.add(
                    node,
                    "py.jwt-unverified",
                    "security",
                    "high",
                    "A JWT is decoded without checking its signature",
                    "Anyone can write a token that says they are anyone: without the signature check, its claims "
                    "are whatever the sender typed.",
                    "Verify it with the key and the algorithms you issue: `jwt.decode(token, key, algorithms=[\"HS256\"])`.",
                )
        if tail in ("CORSMiddleware", "CORS", "add_middleware"):
            self._cors(node)
        if tail == "run" and _is_true(_kw(node, "debug")):
            self.add(
                node,
                "py.debug-on",
                "security",
                "medium",
                "The app runs with `debug=True`",
                "Debug mode shows tracebacks and, in Flask, an interactive console that runs code for whoever "
                "triggers an error.",
                "Read it from the environment, off by default.",
            )
        if callee == "tempfile.mktemp":
            self.add(
                node,
                "py.insecure-tempfile",
                "security",
                "medium",
                "`tempfile.mktemp` names a file without creating it",
                "Between naming the file and opening it, another process can create it first and read or "
                "replace what is written.",
                "Use `tempfile.NamedTemporaryFile()` or `tempfile.mkstemp()`.",
            )
        if tail in ("md5", "sha1") and callee.startswith("hashlib") and not _is_false(_kw(node, "usedforsecurity")):
            secret = _mentions(node, _SECRET_NAME)
            if secret:
                self.add(
                    node,
                    "py.weak-hash",
                    "security",
                    "medium",
                    f"`{tail}` hashes `{secret}`",
                    f"{tail.upper()} is fast and broken: a leaked {tail.upper()} of a password is cracked in seconds.",
                    "Hash passwords with `bcrypt`, `argon2` or `hashlib.scrypt`; sign with `hmac` and SHA-256.",
                )

        # Network calls with no timeout.
        if callee.startswith("requests.") and tail in _REQUESTS_METHODS and _kw(node, "timeout") is None:
            self.add(
                node,
                "py.no-timeout",
                "errors",
                "medium",
                f"`{callee}` has no timeout",
                "`requests` waits forever by default: a server that stops answering holds this call, and "
                "whatever is waiting on it, until the process is killed.",
                "Pass `timeout=` (a few seconds for an API, more for a download).",
            )
        if callee == "urllib.request.urlopen" and _kw(node, "timeout") is None and len(node.args) < 3:
            self.add(
                node,
                "py.no-timeout",
                "errors",
                "medium",
                "`urlopen` has no timeout",
                "It waits as long as the server takes, which can be forever.",
                "Pass `timeout=`.",
            )

        # Blocking calls inside async code.
        if in_async:
            reason = _BLOCKING.get(callee)
            if reason is None and callee.startswith("requests.") and tail in _REQUESTS_METHODS:
                reason = "`requests` waits on the network with the whole event loop held"
            if reason is None and callee.startswith("subprocess.") and tail in ("run", "call", "check_call", "check_output"):
                reason = f"`{callee}` waits for the command with the whole event loop held"
            if reason:
                self.add(
                    node,
                    "py.blocking-in-async",
                    "performance",
                    "medium",
                    f"A blocking call in `async def {self.functions[-1][0]}`",
                    f"{reason}: while it waits, no other request on this process makes progress.",
                    "Use the async form (`asyncio.sleep`, `httpx.AsyncClient`, `asyncio.create_subprocess_exec`) "
                    "or run it with `await asyncio.to_thread(...)`.",
                )

        # Leaks: secrets in logs, error details to the client.
        if self._is_log(callee):
            secret = next((found for a in [*node.args, *[k.value for k in node.keywords]] if (found := _leaks(a))), None)
            if secret:
                self.add(
                    node,
                    "py.secret-in-log",
                    "leakage",
                    "medium",
                    f"`{secret}` is written to a log",
                    "Logs are copied, shipped and kept far longer than secrets should be, and read by people who "
                    "should not hold the credential.",
                    "Log that it was present, or its last four characters, never the value.",
                    "likely",
                )
        # A domain error raised to be shown (`NotFoundError`) is meant for the client;
        # whatever `except Exception` caught is not.
        caught = [c for c in self.caught_broad if c]
        if caught and tail in ("HTTPException", "JSONResponse", "jsonify", "Response", "PlainTextResponse", "abort"):
            exposed = any(
                isinstance(n, ast.Name) and n.id in caught or _dotted(getattr(n, "func", n)) == "traceback.format_exc"
                for a in [*node.args, *[k.value for k in node.keywords]]
                for n in ast.walk(a)
            )
            if exposed:
                self.add(
                    node,
                    "py.error-to-client",
                    "leakage",
                    "medium",
                    "The exception's text is sent to the client",
                    "Exception messages carry file paths, queries, hostnames and sometimes values: details an "
                    "attacker uses to aim the next request.",
                    "Log the exception, and send the client a fixed message with an id to find the log line by.",
                )

    @staticmethod
    def _is_log(callee: str) -> bool:
        if callee == "print":
            return True
        root, _, tail = callee.rpartition(".")
        return bool(root) and tail in ("debug", "info", "warning", "warn", "error", "exception", "critical", "log") and (
            "log" in root.lower() or root in ("self", "structlog")
        )

    def _cors(self, node: ast.Call) -> None:
        origins = _kw(node, "allow_origins") or _kw(node, "origins")
        wildcard = (isinstance(origins, ast.Constant) and origins.value == "*") or (
            isinstance(origins, (ast.List, ast.Tuple)) and any(isinstance(e, ast.Constant) and e.value == "*" for e in origins.elts)
        )
        if not wildcard:
            return
        credentials = _is_true(_kw(node, "allow_credentials")) or _is_true(_kw(node, "supports_credentials"))
        self.add(
            node,
            "py.cors-any-origin",
            "security",
            "high" if credentials else "low",
            "CORS allows every origin" + (" with credentials" if credentials else ""),
            (
                "Any website a signed-in user visits can call this API as that user and read the answers."
                if credentials
                else "Any website can call this API from a visitor's browser. Fine for public data; not for anything "
                "behind a login."
            ),
            "List the origins that should call it.",
        )


#: Each rule's short name, for grouping findings and naming the rule in reports.
LABELS: dict[str, str] = {
    "py.bare-except": "Bare except",
    "py.swallowed-exception": "Exceptions caught and dropped",
    "py.raise-without-cause": "Errors raised again without their cause",
    "py.is-literal": "`is` compared with a literal",
    "py.mutable-default": "Mutable default arguments",
    "py.debug-on": "Debug mode left on",
    "py.insecure-random": "`random` used for secrets",
    "py.tls-off": "Certificate checks turned off",
    "py.eval": "Code run from a string",
    "py.shell-injection": "Shell commands built from values",
    "py.sql-built": "SQL built from values",
    "py.unsafe-deserialization": "Unsafe deserialisation",
    "py.jwt-unverified": "JWTs decoded without checking",
    "py.cors-any-origin": "CORS open to every origin",
    "py.insecure-tempfile": "Temporary files named before they exist",
    "py.weak-hash": "Weak hashes for secrets",
    "py.no-timeout": "Network calls with no timeout",
    "py.blocking-in-async": "Blocking calls in async code",
    "py.secret-in-log": "Secrets written to logs",
    "py.error-to-client": "Exception text sent to clients",
    "py.test-asserts-nothing": "Tests that assert nothing",
}


def inspect(relative_path: str, source: str, is_test: bool) -> list[Issue]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    stem = relative_path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    inspector = _Inspector(is_test, stem, source.splitlines())
    inspector.visit(tree)
    seen: set[tuple[str, int]] = set()
    out: list[Issue] = []
    for issue in inspector.out:
        if (issue.rule, issue.line) not in seen:
            seen.add((issue.rule, issue.line))
            out.append(issue)
    return out


__all__ = ["LABELS", "inspect"]
