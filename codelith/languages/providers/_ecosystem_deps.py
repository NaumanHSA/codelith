"""
Dependencies for the npm and Go ecosystems: what a manifest declares, what a lockfile
pins, and which packages a file imports.

npm package names are what code imports (`import x from "react-dom/client"` is
`react-dom`; a scoped `@tanstack/react-query/devtools` is `@tanstack/react-query`). Go
imports name a module path and a package inside it, so an import belongs to the longest
required module it starts with.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from codelith.languages.base import Declared

NODE_BUILTINS = frozenset(
    {
        "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram",
        "diagnostics_channel", "dns", "domain", "events", "fs", "http", "http2", "https", "inspector", "module", "net",
        "os", "path", "perf_hooks", "process", "punycode", "querystring", "readline", "repl", "stream", "string_decoder",
        "sys", "timers", "tls", "trace_events", "tty", "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib", "test",
    }
)

#: Installed to be run, or used by tools and config, not imported by the code.
NODE_NOT_IMPORTED = re.compile(
    r"^(@types/.*|typescript|vite|@vitejs/.*|eslint.*|@eslint/.*|prettier.*|oxfmt|oxlint|tailwindcss|@tailwindcss/.*|postcss.*|"
    r"autoprefixer|vitest|jest|@testing-library/.*|playwright|@playwright/.*|husky|lint-staged|tsx|ts-node|nodemon|"
    r"concurrently|rimraf|cross-env|@fontsource.*|.*-plugin.*|.*-loader|babel.*|@babel/.*|webpack.*|rollup.*|esbuild|"
    r"turbo|nx|lerna|serve|http-server|@mermaid-js/mermaid-cli|mermaid-cli)$"
)


#: `import("x")` and `require("x")`.
DYNAMIC_IMPORT = re.compile(r"""(?:\bimport|\brequire)\(\s*['"]([^'"]+)['"]\s*\)""")

#: A frontend built by a bundler: its development dependencies are bundled in at
#: build time, so importing one from shipped code is not a gap.
BUNDLERS = re.compile(r"^(vite|webpack|rollup|parcel|esbuild|next|nuxt|@sveltejs/kit|astro|react-scripts|@angular/cli)$")


def node_declared(relative_path: str, source: str) -> list[Declared]:
    if PurePosixPath(relative_path).name != "package.json":
        return []
    try:
        data = json.loads(source)
    except ValueError:
        return []
    lines = source.splitlines()

    def line_of(name: str) -> int | None:
        needle = f'"{name}"'
        return next((i for i, text in enumerate(lines, start=1) if text.strip().startswith(needle)), None)

    out: list[Declared] = []
    for section, dev in (("dependencies", False), ("devDependencies", True), ("optionalDependencies", False)):
        for name, spec in (data.get(section) or {}).items():
            out.append(Declared(str(name), str(spec), dev, line_of(str(name)), "npm"))
    return out


def node_locked(relative_path: str, source: str) -> dict[str, str]:
    name = PurePosixPath(relative_path).name
    out: dict[str, str] = {}
    if name in ("package-lock.json", "npm-shrinkwrap.json"):
        try:
            data = json.loads(source)
        except ValueError:
            return {}
        for key, info in (data.get("packages") or {}).items():
            # Only what sits directly in node_modules: nested copies are someone else's.
            if key.startswith("node_modules/") and key.count("node_modules/") == 1 and isinstance(info, dict) and info.get("version"):
                out[key[len("node_modules/") :]] = str(info["version"])
        for key, info in (data.get("dependencies") or {}).items():  # lockfile v1
            if isinstance(info, dict) and info.get("version"):
                out.setdefault(key, str(info["version"]))
    elif name == "pnpm-lock.yaml":
        try:
            import yaml

            data = yaml.safe_load(source) or {}
        except Exception:  # a lockfile that does not parse pins nothing
            return {}
        for importer in (data.get("importers") or {}).values():
            for section in ("dependencies", "devDependencies", "optionalDependencies"):
                for pkg, info in ((importer or {}).get(section) or {}).items():
                    version = info.get("version") if isinstance(info, dict) else info
                    if version:
                        out.setdefault(str(pkg), str(version).split("(", 1)[0])
        for pkg, info in ((data.get("dependencies") or {}) if not data.get("importers") else {}).items():
            version = info.get("version") if isinstance(info, dict) else info
            if version:
                out.setdefault(str(pkg), str(version).split("(", 1)[0])
    elif name == "yarn.lock":
        current: list[str] = []
        for text in source.splitlines():
            if text and not text.startswith((" ", "#")) and text.rstrip().endswith(":"):
                current = [re.sub(r"@[^@]*$", "", spec.strip().strip('"')) for spec in text.rstrip(":").split(",")]
            elif text.strip().startswith("version ") and current:
                version = text.strip().split(" ", 1)[1].strip('"')
                for pkg in current:
                    out.setdefault(pkg, version)
                current = []
    return out


def node_root(target: str) -> str | None:
    """The package an import specifier names, or None for a local or aliased one."""
    if not target or target.startswith((".", "/", "~", "#")) or target.startswith("@/"):
        return None
    if target.startswith("node:"):
        return None
    parts = target.split("/")
    root = "/".join(parts[:2]) if target.startswith("@") and len(parts) > 1 else parts[0]
    if root in NODE_BUILTINS or root.startswith("virtual:") or "?" in root:
        return None
    return root


def go_declared(relative_path: str, source: str) -> list[Declared]:
    if PurePosixPath(relative_path).name != "go.mod":
        return []
    out: list[Declared] = []
    block = False
    for i, raw in enumerate(source.splitlines(), start=1):
        text = raw.split("//", 1)[0].strip()
        indirect = "// indirect" in raw
        if text.startswith("require ("):
            block = True
            continue
        if block and text == ")":
            block = False
            continue
        if block or text.startswith("require "):
            parts = text.removeprefix("require ").split()
            if len(parts) >= 2:
                out.append(Declared(parts[0], parts[1], indirect, i, "Go"))
    return out


def go_root(target: str) -> str | None:
    """A Go import that is not the standard library (whose first element has no dot)."""
    if not target or "." not in target.split("/", 1)[0]:
        return None
    return target


__all__ = ["BUNDLERS", "DYNAMIC_IMPORT", "NODE_BUILTINS", "NODE_NOT_IMPORTED", "go_declared", "go_root", "node_declared", "node_locked", "node_root"]
