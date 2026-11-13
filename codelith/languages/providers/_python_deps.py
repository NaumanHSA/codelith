"""
What QA's dependency audit needs from Python: what is declared, what is locked, what is
imported, and which syntax needs which version.

The hard part is names. A distribution is installed as `PyYAML` and imported as `yaml`;
`beautifulsoup4` as `bs4`. Names are compared after PEP 503 normalisation, then through
a table of the mismatches people actually hit. A package that is never imported on
purpose (a server run from the command line, a database driver named in a URL, a type
stub) is not "unused".
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import PurePosixPath

from codelith.languages.base import Declared

_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;#]*)")

#: Import name to the distributions that provide it, where the two differ.
IMPORT_TO_DIST: dict[str, tuple[str, ...]] = {
    "yaml": ("pyyaml",),
    "PIL": ("pillow",),
    "cv2": ("opencv-python", "opencv-python-headless", "opencv-contrib-python"),
    "sklearn": ("scikit-learn",),
    "skimage": ("scikit-image",),
    "bs4": ("beautifulsoup4",),
    "dateutil": ("python-dateutil",),
    "jwt": ("pyjwt",),
    "jose": ("python-jose",),
    "dotenv": ("python-dotenv",),
    "multipart": ("python-multipart",),
    "slugify": ("python-slugify",),
    "docx": ("python-docx",),
    "pptx": ("python-pptx",),
    "magic": ("python-magic",),
    "attr": ("attrs",),
    "Crypto": ("pycryptodome",),
    "OpenSSL": ("pyopenssl",),
    "serial": ("pyserial",),
    "usb": ("pyusb",),
    "git": ("gitpython",),
    "zmq": ("pyzmq",),
    "fitz": ("pymupdf",),
    "MySQLdb": ("mysqlclient",),
    "psycopg2": ("psycopg2", "psycopg2-binary"),
    "gi": ("pygobject",),
    "win32api": ("pywin32",),
    "websocket": ("websocket-client",),
    "google": ("protobuf", "google-api-python-client", "google-cloud-storage", "google-generativeai", "google-genai"),
    "pydantic_settings": ("pydantic-settings",),
    "structlog": ("structlog",),
    "opentelemetry": ("opentelemetry-api", "opentelemetry-sdk"),
    "langgraph": ("langgraph",),
    "langchain_core": ("langchain-core",),
    "prometheus_client": ("prometheus-client",),
    "jinja2": ("jinja2",),
    "markdown": ("markdown",),
    "tree_sitter": ("tree-sitter",),
    "markdown_it": ("markdown-it-py",),
    "github": ("pygithub",),
    "gitlab": ("python-gitlab",),
    "telegram": ("python-telegram-bot",),
    "discord": ("discord-py",),
    "mcp": ("mcp",),
    "langchain": ("langchain",),
}

#: Roots several distributions share: the import path is compared further down
#: (`opentelemetry.exporter.otlp` is `opentelemetry-exporter-otlp`).
NAMESPACES = frozenset({"opentelemetry", "google", "azure", "zope", "jaraco", "sphinxcontrib", "backports", "ruamel"})

#: Installed to be run or loaded by name, not imported: never "unused".
NOT_IMPORTED = re.compile(
    r"^(uvicorn|gunicorn|hypercorn|daphne|celery|alembic|pytest.*|.*-stubs|types-.*|mypy|ruff|black|isort|flake8.*|pylint|"
    r"coverage|pre-commit|tox|nox|ipython|ipykernel|jupyter.*|mkdocs.*|sphinx.*|twine|build|wheel|setuptools|pip|"
    r"psycopg.*|asyncpg|aiosqlite|pymysql|mysqlclient|cx-oracle|oracledb|pyodbc|python-multipart|email-validator|"
    r"uvloop|httptools|watchfiles|websockets|orjson|ujson|greenlet|bcrypt|passlib.*|argon2-cffi|cryptography|"
    r"debugpy|hatch.*|poetry.*|pdm.*|flit.*|cython|nuitka|pyinstaller|playwright|selenium)$"
)

#: Syntax that needs a newer Python than it looks: node type to (feature, version).
_SYNTAX: tuple[tuple[str, str, str], ...] = (
    ("Match", "a `match` statement", "3.10"),
    ("TryStar", "`except*`", "3.11"),
    ("TypeAlias", "a `type` statement", "3.12"),
)
#: Standard library modules added in a version, by the version.
_STDLIB_SINCE = {"tomllib": "3.11", "graphlib": "3.9", "zoneinfo": "3.9"}

_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dists_for(imported: str) -> set[str]:
    """The distributions an import can come from."""
    first = imported.split(".", 1)[0]
    return {
        normalise(imported),
        normalise(first),
        *(normalise(d) for d in IMPORT_TO_DIST.get(imported, ())),
        *(normalise(d) for d in IMPORT_TO_DIST.get(first, ())),
    }


def provides(package: str, imported: str) -> bool:
    """Whether a distribution is what an import comes from."""
    want = normalise(package)
    return want in dists_for(imported) or normalise(imported).startswith(want + "-")


def is_builtin(root: str) -> bool:
    return root.split(".", 1)[0] in _STDLIB


def declared(relative_path: str, source: str) -> list[Declared]:
    name = PurePosixPath(relative_path).name
    lines = source.splitlines()

    def line_of(pkg: str) -> int | None:
        """The line declaring it: quoted in a list (`"pkg>=1"`), or a key (`pkg = "^1"`)."""
        quoted = re.compile(r"[\"']\s*" + re.escape(pkg) + r"(?=[\s\[<>=!~;,\"']|$)", re.IGNORECASE)
        keyed = re.compile(r"^\s*" + re.escape(pkg) + r"\s*=", re.IGNORECASE)
        for i, text in enumerate(lines, start=1):
            if quoted.search(text) or keyed.search(text):
                return i
        return None

    if name.startswith("requirements") and name.endswith((".txt", ".in")):
        dev = bool(re.search(r"(dev|test|lint|doc)", name))
        out: list[Declared] = []
        for i, raw in enumerate(lines, start=1):
            text = raw.split("#", 1)[0].strip()
            if not text or text.startswith(("-", "git+", "http")):
                continue
            if m := _REQ.match(text):
                out.append(Declared(m.group(1), m.group(3).strip(), dev, i, "PyPI"))
        return out
    if name == "pyproject.toml":
        try:
            import tomllib

            data = tomllib.loads(source)
        except Exception:  # a broken manifest declares nothing we can read
            return []
        out = []
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        for spec in project.get("dependencies") or []:
            if isinstance(spec, str) and (m := _REQ.match(spec)):
                out.append(Declared(m.group(1), m.group(3).strip(), False, line_of(m.group(1)), "PyPI"))
        groups = dict(project.get("optional-dependencies") or {})
        groups.update(data.get("dependency-groups") or {})
        for group, specs in groups.items():
            dev = bool(re.search(r"(dev|test|lint|doc|type)", str(group)))
            for spec in specs if isinstance(specs, list) else []:
                if isinstance(spec, str) and (m := _REQ.match(spec)):
                    out.append(Declared(m.group(1), m.group(3).strip(), dev, line_of(m.group(1)), "PyPI"))
        poetry = (data.get("tool") or {}).get("poetry") or {}
        for section, dev in (("dependencies", False), ("dev-dependencies", True)):
            for pkg, spec in (poetry.get(section) or {}).items():
                if pkg.lower() != "python":
                    out.append(Declared(pkg, spec if isinstance(spec, str) else str((spec or {}).get("version", "")), dev, line_of(pkg), "PyPI"))
        return out
    return []


def locked(relative_path: str, source: str) -> dict[str, str]:
    name = PurePosixPath(relative_path).name
    out: dict[str, str] = {}
    if name in ("poetry.lock", "uv.lock", "pdm.lock"):
        try:
            import tomllib

            data = tomllib.loads(source)
        except Exception:  # a lockfile that does not parse pins nothing
            return {}
        for pkg in data.get("package") or []:
            if isinstance(pkg, dict) and pkg.get("name") and pkg.get("version"):
                out[normalise(str(pkg["name"]))] = str(pkg["version"])
    elif name == "Pipfile.lock":
        try:
            data = json.loads(source)
        except ValueError:
            return {}
        for section in ("default", "develop"):
            for pkg, info in (data.get(section) or {}).items():
                version = str((info or {}).get("version", "")).lstrip("=")
                if version:
                    out[normalise(pkg)] = version
    return out


def import_roots(source: str) -> list[tuple[str, int]]:
    """Top-level names of absolute imports, with the line of each first import."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    seen: dict[str, int] = {}

    def key(module: str) -> str:
        parts = module.split(".")
        return ".".join(parts[:3]) if parts[0] in NAMESPACES else parts[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                seen.setdefault(key(alias.name), node.lineno)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            seen.setdefault(key(node.module), node.lineno)
    return sorted(seen.items(), key=lambda kv: kv[1])


def syntax_needs(source: str) -> list[tuple[str, str, int]]:
    """`(feature, minimum version, line)` for syntax and modules newer than 3.8."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    out: list[tuple[str, str, int]] = []
    found: set[str] = set()
    for node in ast.walk(tree):
        kind = type(node).__name__
        for name, feature, version in _SYNTAX:
            if kind == name and feature not in found:
                found.add(feature)
                out.append((feature, version, getattr(node, "lineno", 1)))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and getattr(node, "type_params", None):
            if "generic parameters (`def f[T]`)" not in found:
                found.add("generic parameters (`def f[T]`)")
                out.append(("generic parameters (`def f[T]`)", "3.12", node.lineno))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                root = n.split(".", 1)[0]
                if root in _STDLIB_SINCE and f"`{root}`" not in found:
                    found.add(f"`{root}`")
                    out.append((f"the `{root}` module", _STDLIB_SINCE[root], node.lineno))
    return out


__all__ = ["IMPORT_TO_DIST", "NAMESPACES", "NOT_IMPORTED", "declared", "dists_for", "provides", "import_roots", "is_builtin", "locked", "normalise", "syntax_needs"]
