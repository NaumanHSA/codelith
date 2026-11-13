"""
What each ecosystem declares, locks and imports, as QA's dependency audit reads it —
including the names that differ between installing and importing.
"""

from __future__ import annotations

import textwrap

from codelith.apps.qa.checks.dependencies import satisfies
from codelith.apps.qa.checks.online import _bump
from codelith.languages import registry

PY = registry.for_path("a.py")
TS = registry.for_path("a.ts")
GO = registry.for_path("a.go")

PYPROJECT = textwrap.dedent(
    """
    [project]
    requires-python = ">=3.9"
    dependencies = [
        "fastapi>=0.110",
        "PyYAML",
    ]

    [project.optional-dependencies]
    dev = ["pytest>=8"]
    """
)


class TestPython:
    def test_declared_with_versions_and_dev(self) -> None:
        got = [(d.name, d.spec, d.dev, d.line) for d in PY.declared("pyproject.toml", PYPROJECT)]
        assert got == [("fastapi", ">=0.110", False, 5), ("PyYAML", "", False, 6), ("pytest", ">=8", True, 10)]

    def test_requirements_files(self) -> None:
        got = PY.declared("requirements-dev.txt", "requests==2.31.0  # http\n-r base.txt\nblack\n")
        assert [(d.name, d.spec, d.dev) for d in got] == [("requests", "==2.31.0", True), ("black", "", True)]

    def test_imports_not_the_standard_library(self) -> None:
        src = "import os, yaml\nfrom fastapi import APIRouter\nfrom . import x\nimport opentelemetry.exporter.otlp.proto\n"
        assert PY.imported_packages("a.py", src) == [("yaml", 1), ("fastapi", 2), ("opentelemetry.exporter.otlp", 4)]

    def test_install_and_import_names(self) -> None:
        assert PY.provides("PyYAML", "yaml") and PY.provides("beautifulsoup4", "bs4")
        assert PY.provides("opentelemetry-exporter-otlp", "opentelemetry.exporter.otlp")
        assert not PY.provides("opentelemetry-exporter-otlp", "opentelemetry.trace")
        assert PY.never_imported("uvicorn") and PY.never_imported("types-requests")

    def test_a_poetry_lock(self) -> None:
        lock = '[[package]]\nname = "Requests"\nversion = "2.31.0"\n'
        assert PY.locked("poetry.lock", lock) == {"requests": "2.31.0"}

    def test_syntax_newer_than_it_looks(self) -> None:
        src = "import tomllib\nmatch x:\n    case 1:\n        pass\n"
        assert [(f, v) for f, v, _ in PY.syntax_needs("a.py", src)] == [("the `tomllib` module", "3.11"), ("a `match` statement", "3.10")]


class TestNode:
    def test_declared_and_imported(self) -> None:
        pkg = '{\n  "dependencies": {\n    "react": "^19.0.0"\n  },\n  "devDependencies": {\n    "vite": "^7.0.0"\n  }\n}\n'
        assert [(d.name, d.dev, d.line) for d in TS.declared("package.json", pkg)] == [("react", False, 3), ("vite", True, 6)]
        src = "import React from 'react'\nimport { x } from '@scope/pkg/sub'\nimport a from './a'\nconst m = await import('mermaid')\n"
        assert TS.imported_packages("a.ts", src) == [("react", 1), ("@scope/pkg", 2), ("mermaid", 4)]

    def test_lockfiles(self) -> None:
        npm = '{"packages": {"": {}, "node_modules/react": {"version": "19.0.1"}, "node_modules/a/node_modules/b": {"version": "1.0.0"}}}'
        assert TS.locked("package-lock.json", npm) == {"react": "19.0.1"}
        pnpm = "lockfileVersion: '9.0'\nimporters:\n  .:\n    dependencies:\n      react:\n        specifier: ^19.0.0\n        version: 19.0.1(foo@1)\n"
        assert TS.locked("pnpm-lock.yaml", pnpm) == {"react": "19.0.1"}


class TestGo:
    def test_require_block_and_imports(self) -> None:
        mod = "module x\n\ngo 1.22\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgolang.org/x/sys v0.15.0 // indirect\n)\n"
        got = [(d.name, d.spec, d.dev) for d in GO.declared("go.mod", mod)]
        assert got == [("github.com/gin-gonic/gin", "v1.9.1", False), ("golang.org/x/sys", "v0.15.0", True)]
        assert GO.provides("github.com/gin-gonic/gin", "github.com/gin-gonic/gin/binding")


def test_version_constraints() -> None:
    assert satisfies("PyPI", ">=2.0,<3", "2.5.1") is True
    assert satisfies("PyPI", ">=2.0", "1.9") is False
    assert satisfies("npm", "^1.2.3", "1.9.0") and not satisfies("npm", "^1.2.3", "2.0.0")
    assert satisfies("npm", "^0.3.1", "0.3.9") and not satisfies("npm", "^0.3.1", "0.4.0")
    assert satisfies("npm", "~1.2.3", "1.2.9") and not satisfies("npm", "~1.2.3", "1.3.0")
    assert satisfies("npm", "workspace:*", "1.0.0") is None


def test_a_patch_raises_the_floor_on_its_line() -> None:
    text = '[project]\ndependencies = [\n    "jinja2>=2.10",\n]\n'
    patch = _bump(text, 3, "jinja2", "3.1.4", "PyPI", "pyproject.toml")
    assert patch and '-    "jinja2>=2.10",' in patch and '+    "jinja2>=3.1.4",' in patch
    pkg = '{\n  "dependencies": {\n    "lodash": "^4.17.10"\n  }\n}\n'
    assert '+    "lodash": "^4.17.21"' in _bump(pkg, 3, "lodash", "4.17.21", "npm", "package.json")
