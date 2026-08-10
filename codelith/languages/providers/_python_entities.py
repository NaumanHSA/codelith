"""
Python entity detection: the facts a parser can see that a reader would ask about.

Split out of `python.py` because it is table-driven and grows with every framework,
while the symbol extraction next to it does not. Still inside `app/languages/`, which
is what the architecture rule cares about.

**Precision over recall, everywhere in this file.** These entities are read by the
site planner, the writer, and soon by question answering — a wrong `datastore` entry
propagates into documentation, diagrams and answers simultaneously, and nothing
downstream can tell it was a guess. Every detector here would rather miss a real
thing than invent one, so each is anchored on a construct that is unambiguous:
a known constructor, a framework decorator, a declared table name.

Each returns entities carrying `source_path` and a line, so everything is clickable
back to the code that justified it.
"""

from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath

from codelith.knowledge.constants import EntityKind
from codelith.languages.base import DetectedEntity, Symbol

# ── Datastores ────────────────────────────────────────────────────────────────
#
# Keyed on the constructor, because that is the moment a connection is defined.
# A bare `import redis` says the dependency exists; `redis.Redis(...)` says this
# system stores something there.

_DATASTORE_CALLS: dict[str, tuple[str, str]] = {
    "create_engine": ("sql", "SQLAlchemy engine"),
    "create_async_engine": ("sql", "SQLAlchemy async engine"),
    "AsyncGraphDatabase.driver": ("graph", "Neo4j"),
    "GraphDatabase.driver": ("graph", "Neo4j"),
    "MongoClient": ("document", "MongoDB"),
    "AsyncIOMotorClient": ("document", "MongoDB"),
    "Redis": ("key_value", "Redis"),
    "Redis.from_url": ("key_value", "Redis"),
    "StrictRedis": ("key_value", "Redis"),
    "ConnectionPool.from_url": ("key_value", "Redis"),
    "connect": ("sql", "DB-API connection"),
    "chromadb.Client": ("vector", "Chroma"),
    "chromadb.PersistentClient": ("vector", "Chroma"),
    "QdrantClient": ("vector", "Qdrant"),
    "Pinecone": ("vector", "Pinecone"),
    "weaviate.Client": ("vector", "Weaviate"),
}

#: `connect` is far too common a name to trust on its own.
_DATASTORE_REQUIRES_MODULE = {"connect": {"psycopg", "psycopg2", "asyncpg", "sqlite3", "aiosqlite"}}

#: `boto3.client("s3")` — the service name is the first argument, not the callee.
_BOTO_SERVICES = {
    "s3": ("object_store", "Amazon S3"),
    "dynamodb": ("document", "DynamoDB"),
    "sqs": ("queue", "Amazon SQS"),
    "sns": ("queue", "Amazon SNS"),
    "rds": ("sql", "Amazon RDS"),
}

# ── External APIs ─────────────────────────────────────────────────────────────

_SDK_CLIENTS: dict[str, str] = {
    "OpenAI": "OpenAI", "AsyncOpenAI": "OpenAI",
    "Anthropic": "Anthropic", "AsyncAnthropic": "Anthropic",
    "Together": "Together", "Groq": "Groq", "Cohere": "Cohere",
    "Mistral": "Mistral", "HuggingFaceHub": "Hugging Face",
    "Stripe": "Stripe", "Twilio": "Twilio", "SendGridAPIClient": "SendGrid",
    "WebClient": "Slack", "Github": "GitHub",
}

_HTTP_CLIENTS = {"AsyncClient", "Client", "ClientSession", "Session"}

#: An absolute URL in a string literal. Localhost is configuration, not an integration.
_URL = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

# ── CLI ───────────────────────────────────────────────────────────────────────

_CLI_DECORATORS = re.compile(r"^(?:\w+\.)?(?:command|group)\s*\(")
_ARGPARSE = "ArgumentParser"

# ── Scheduled work ────────────────────────────────────────────────────────────

_TASK_DECORATORS = re.compile(r"^(?:\w+\.)?(?:task|shared_task|periodic_task|scheduled_job)\b")
#: `"*/5 * * * *"` — five or six whitespace-separated cron fields.
_CRON = re.compile(r"^(\S+\s+){4,5}\S+$")
_CRON_TOKENS = re.compile(r"[\d*/,\-]")

# ── Events ────────────────────────────────────────────────────────────────────

_DISPATCH_METHODS = {"delay", "apply_async", "send_task"}
_PUBSUB_METHODS = {"publish", "subscribe", "psubscribe", "xadd"}

# ── Services ──────────────────────────────────────────────────────────────────
#
# Naming convention only. Anything looser (every class instantiated at module
# scope, say) sweeps in dataclasses, enums and config objects.
_SERVICE_SUFFIXES = ("Service", "Repository", "Store", "Client", "Gateway", "Manager", "Broker")


def _dotted(node: ast.expr) -> str:
    """`a.b.c` for an attribute chain, `a` for a name, `""` for anything else."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _literal(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _kwarg(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name:
            return _literal(kw.value)
    return None


def has_main_guard(source: str) -> bool:
    """
    A real `if __name__ == "__main__":` block.

    Substring matching finds the comment that *documents* the idiom as readily as the
    idiom — this provider's own explanatory comment was making it an entrypoint of
    the system it was analysing.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        left, comparators = node.test.left, node.test.comparators
        if (
            isinstance(left, ast.Name) and left.id == "__name__"
            and comparators and _literal(comparators[0]) == "__main__"
        ):
            return True
    return False


def _is_env_helper(callee: str) -> bool:
    """Whether a call looks like a project's own wrapper around the environment."""
    tail = (callee or "").rsplit(".", 1)[-1].lower()
    return tail.startswith("env_") or tail.endswith("_env") or tail in ("env", "getenv")


#: Base classes that make a class's fields into environment variables. The
#: pydantic-settings convention, and the `BaseSettings` name is stable across v1 and
#: v2 — the import path is not, so it is matched on the name.
_SETTINGS_BASES = frozenset({"BaseSettings", "PydanticBaseSettingsSource"})

#: Fields that are configuration of the settings mechanism, not settings themselves.
_SETTINGS_META = frozenset({"model_config", "Config", "__slots__"})


def _settings_prefix(node: ast.ClassDef) -> str | None:
    """
    The `env_prefix` a settings class declares, or `""` if it declares none.

    `None` means this is not a settings class at all — the caller needs to tell
    "no prefix" apart from "not applicable", and both are falsy.
    """
    bases = {_dotted(b).rsplit(".", 1)[-1] for b in node.bases}
    if not bases & _SETTINGS_BASES:
        return None

    for item in node.body:
        # v2: `model_config = SettingsConfigDict(env_prefix="NS_")`, annotated or not
        # — `model_config: SettingsConfigDict = ...` is an `AnnAssign` and reading
        # only `Assign` dropped the prefix silently, which is worse than dropping the
        # class: every field came back unprefixed and therefore wrong.
        targets = (
            item.targets if isinstance(item, ast.Assign)
            else [item.target] if isinstance(item, ast.AnnAssign)
            else []
        )
        if any(isinstance(t, ast.Name) and t.id == "model_config" for t in targets):
            if isinstance(getattr(item, "value", None), ast.Call):
                for keyword in item.value.keywords:
                    if keyword.arg == "env_prefix":
                        return _literal(keyword.value) or ""
        # v1: `class Config: env_prefix = "NS_"`
        if isinstance(item, ast.ClassDef) and item.name == "Config":
            for inner in item.body:
                if isinstance(inner, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "env_prefix" for t in inner.targets
                ):
                    return _literal(inner.value) or ""
    return ""


def settings_env_vars(tree: ast.Module) -> list[tuple[str, int]]:
    """
    Variables declared by a settings class, which name themselves nowhere.

    `class ServerSettings(BaseSettings)` with `env_prefix="NS_"` and a field `port`
    declares `NS_PORT`. The string never appears in the source — it is assembled at
    runtime from the prefix and the field name — so no pattern over call sites can
    find it, however clever.

    Found by scoring answers: asked what environment variables neurosurfer needs, the
    model named `NS_HOST`, `NS_PORT` and `NS_LOG_LEVEL`. All three are real, none
    were in the knowledge base, and all three were reported to the reader as invented
    citations. Codelith uses the same idiom in `app/config.py`, so until now
    it could not document its own configuration.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        prefix = _settings_prefix(node)
        if prefix is None:
            continue

        for item in node.body:
            # An annotated field is the declaration. A bare assignment is usually
            # metadata, and `x: int = 5` and `x: int` are both settings.
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            name = item.target.id
            if name in _SETTINGS_META or name.startswith("_"):
                continue
            found.append((f"{prefix}{name}".upper(), item.lineno))
    return found


def env_vars(source: str) -> list[DetectedEntity]:
    """
    Environment variables the code reads.

    AST-based for the same reason as `has_main_guard`: the regex version extracted a
    variable named `X` from the comment `#: os.getenv("X")`.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []

    out: list[DetectedEntity] = []
    seen: set[str] = set()

    def record(name: str | None, line: int) -> None:
        if name and name not in seen and name.replace("_", "").isalnum():
            seen.add(name)
            out.append(DetectedEntity(kind=EntityKind.ENV_VAR, name=name, line=line))

    for name, line in settings_env_vars(tree):
        record(name, line)

    for node in ast.walk(tree):
        # os.getenv("X") / os.environ.get("X")
        if isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee in ("os.getenv", "os.environ.get", "getenv", "environ.get") and node.args:
                record(_literal(node.args[0]), node.lineno)
            # A project that reads more than two variables writes a helper, and then
            # `os.getenv` never appears at the call sites again. neurosurfer's
            # `env_int("CONTEXT_WINDOW", …)` and `env_bool_opt("SUPPORTS_VISION")`
            # were both missed, and a question-answering model that read the file
            # found them — it should not be better informed than the knowledge base.
            #
            # Narrow on purpose: the callee has to be named for the environment, and
            # the argument has to be a SCREAMING_CASE literal. `env_int(timeout)` and
            # `prepare_environment("staging")` are not reads.
            elif node.args and _is_env_helper(callee):
                name = _literal(node.args[0])
                if name and name.isupper():
                    record(name, node.lineno)
        # os.environ["X"]
        elif isinstance(node, ast.Subscript) and _dotted(node.value) == "os.environ":
            record(_literal(node.slice), node.lineno)

    return out


def detect(
    relative_path: str, source: str, symbols: list[Symbol], imported_roots: set[str]
) -> list[DetectedEntity]:
    """Every entity kind this module knows how to spot, for one file."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []

    found: list[DetectedEntity] = []
    found += _datastores(tree, imported_roots)
    found += _external_apis(tree, source)
    found += _cli_commands(tree, symbols)
    found += _scheduled(tree, symbols)
    found += _events(tree)
    found += _services(symbols, relative_path)
    return found


def _datastores(tree: ast.AST, imported_roots: set[str]) -> list[DetectedEntity]:
    out: list[DetectedEntity] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _dotted(node.func)
        if not callee:
            continue

        # boto3.client("s3") — the service is the argument.
        if callee in ("boto3.client", "boto3.resource") and node.args:
            service = _literal(node.args[0])
            if service and (entry := _BOTO_SERVICES.get(service)):
                kind, label = entry
                out.append(DetectedEntity(
                    kind=EntityKind.DATASTORE, name=label,
                    data={"engine": kind, "via": "boto3", "service": service},
                    line=node.lineno,
                ))
            continue

        entry = _DATASTORE_CALLS.get(callee) or _DATASTORE_CALLS.get(callee.split(".")[-1])
        if not entry:
            continue
        bare = callee.split(".")[-1]
        # `connect` only counts when the file actually imported a database driver.
        if (required := _DATASTORE_REQUIRES_MODULE.get(bare)) and not (required & imported_roots):
            continue
        kind, label = entry
        out.append(DetectedEntity(
            kind=EntityKind.DATASTORE, name=label,
            data={"engine": kind, "constructor": callee}, line=node.lineno,
        ))
    return out


def _external_apis(tree: ast.AST, source: str) -> list[DetectedEntity]:
    out: list[DetectedEntity] = []
    seen: set[str] = set()
    docstrings = _docstring_ids(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _dotted(node.func)
        bare = callee.split(".")[-1] if callee else ""

        if vendor := _SDK_CLIENTS.get(bare):
            if vendor not in seen:
                seen.add(vendor)
                out.append(DetectedEntity(
                    kind=EntityKind.EXTERNAL_API, name=vendor,
                    data={"via": "sdk", "client": callee}, line=node.lineno,
                ))
            continue

        # An HTTP client is only an integration if we can say what it talks to.
        if bare in _HTTP_CLIENTS and (base := _kwarg(node, "base_url")):
            if host := _host(base):
                if host not in seen:
                    seen.add(host)
                    out.append(DetectedEntity(
                        kind=EntityKind.EXTERNAL_API, name=host,
                        data={"via": "http", "base_url": base}, line=node.lineno,
                    ))

    # Absolute URLs in real string literals — not comments, not docstrings, and not
    # documentation placeholders. Scanning raw source found `example.com` in a
    # Docusaurus config template and recorded it as a system integration.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        for match in _URL.finditer(node.value):
            host = match.group(1)
            if host not in seen and not _is_placeholder(host):
                seen.add(host)
                out.append(DetectedEntity(
                    kind=EntityKind.EXTERNAL_API, name=host,
                    data={"via": "url"}, line=node.lineno,
                ))
    return out


#: Hosts that appear in templates and examples rather than in real integrations.
_PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "myorg.com", "yourdomain.com")


def _is_placeholder(host: str) -> bool:
    return host.endswith(_PLACEHOLDER_HOSTS)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Identity of every docstring node, so prose is not mined for facts."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            out.add(id(body[0].value))
    return out


def _host(url: str) -> str | None:
    match = _URL.search(url)
    return match.group(1) if match else None


def _cli_commands(tree: ast.AST, symbols: list[Symbol]) -> list[DetectedEntity]:
    out: list[DetectedEntity] = []
    for symbol in symbols:
        for decorator in symbol.decorators:
            if _CLI_DECORATORS.match(decorator) and not decorator.startswith(("app.get", "router.")):
                out.append(DetectedEntity(
                    kind=EntityKind.CLI_COMMAND, name=symbol.name,
                    data={"handler": symbol.qualified_name, "decorator": decorator},
                    line=symbol.line,
                ))
                break

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted(node.func).split(".")[-1] == _ARGPARSE:
            name = _kwarg(node, "prog") or "argparse CLI"
            out.append(DetectedEntity(
                kind=EntityKind.CLI_COMMAND, name=name,
                data={"framework": "argparse"}, line=node.lineno,
            ))
    return out


def _scheduled(tree: ast.AST, symbols: list[Symbol]) -> list[DetectedEntity]:
    out: list[DetectedEntity] = []
    for symbol in symbols:
        for decorator in symbol.decorators:
            if _TASK_DECORATORS.match(decorator):
                out.append(DetectedEntity(
                    kind=EntityKind.SCHEDULED_TASK, name=symbol.qualified_name,
                    data={"decorator": decorator, "trigger": "task"}, line=symbol.line,
                ))
                break

    # Cron expressions in string literals — a beat schedule, a crontab entry.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.strip()
            fields = text.split()
            if (
                5 <= len(fields) <= 6
                and _CRON.match(text)
                and all(_CRON_TOKENS.fullmatch(f) for f in fields)
            ):
                out.append(DetectedEntity(
                    kind=EntityKind.SCHEDULED_TASK, name=text,
                    data={"trigger": "cron"}, line=node.lineno,
                ))
    return out


def _events(tree: ast.AST) -> list[DetectedEntity]:
    out: list[DetectedEntity] = []
    seen: set[tuple[str, str]] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr

        if method in _DISPATCH_METHODS:
            target = _dotted(node.func.value) or "task"
            if (target, "dispatch") not in seen:
                seen.add((target, "dispatch"))
                out.append(DetectedEntity(
                    kind=EntityKind.EVENT, name=target,
                    data={"direction": "dispatch", "method": method}, line=node.lineno,
                ))

        elif method in _PUBSUB_METHODS and node.args:
            if channel := _literal(node.args[0]):
                if (channel, method) not in seen:
                    seen.add((channel, method))
                    out.append(DetectedEntity(
                        kind=EntityKind.EVENT, name=channel,
                        data={
                            "direction": "publish" if method in ("publish", "xadd") else "subscribe",
                            "method": method,
                        },
                        line=node.lineno,
                    ))
    return out


def _services(symbols: list[Symbol], relative_path: str) -> list[DetectedEntity]:
    """
    Classes that are the system's own moving parts.

    Naming convention rather than instantiation analysis: `*Service`, `*Repository`,
    `*Client`. Private classes are skipped — `_TrimResult` is an implementation
    detail, not a component anyone asks about.
    """
    out: list[DetectedEntity] = []
    for symbol in symbols:
        if str(symbol.kind) != "class" or symbol.parent or symbol.name.startswith("_"):
            continue
        if symbol.name.endswith(_SERVICE_SUFFIXES):
            out.append(DetectedEntity(
                kind=EntityKind.SERVICE, name=symbol.name,
                data={"module": PurePosixPath(relative_path).parent.as_posix()},
                line=symbol.line,
            ))
    return out


__all__ = ["detect"]
