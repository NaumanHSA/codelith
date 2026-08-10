"""
Entities identified by what a file *is*, not by what language it is written in.

A `docker-compose.yml` is infrastructure whether the project is Python or Go, and no
`LanguageProvider` owns `.yml`. Putting these in a provider would mean every new
language re-declaring that Dockerfiles are infrastructure; putting them in an agent
would spread file-type knowledge across the pipeline. They live here, once.

Same rule as the language detectors: anchored on unambiguous filenames rather than
on guesses about content, because a wrong entity reaches documentation, diagrams and
answers at the same time and none of them can tell it was inferred.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from codelith.knowledge.constants import EntityKind
from codelith.languages.registry import registry

#: Exact filenames, and what each one configures. Extensions alone are not enough —
#: `.yml` is a CI pipeline, a compose file or a Helm chart depending on the name.
_CONFIG_FILES: dict[str, str] = {
    ".env": "environment", ".env.example": "environment", ".env.sample": "environment",
    ".env.template": "environment", ".env.local": "environment",
    "pyproject.toml": "build", "setup.cfg": "build", "setup.py": "build",
    "package.json": "build", "tsconfig.json": "build", "go.mod": "build",
    "Cargo.toml": "build", "pom.xml": "build", "build.gradle": "build",
    "alembic.ini": "migrations", "pytest.ini": "testing", "tox.ini": "testing",
    "Makefile": "build", "justfile": "build",
    ".pre-commit-config.yaml": "linting", ".editorconfig": "linting",
    "ruff.toml": "linting", ".ruff.toml": "linting", "mypy.ini": "linting",
    ".eslintrc.json": "linting", ".prettierrc": "linting",
    "nginx.conf": "serving", "gunicorn.conf.py": "serving",
}

#: Infrastructure, by filename or by the directory it sits in.
_INFRA_FILES: dict[str, str] = {
    "Dockerfile": "container image",
    "docker-compose.yml": "container orchestration",
    "docker-compose.yaml": "container orchestration",
    "compose.yml": "container orchestration",
    "compose.yaml": "container orchestration",
    "Procfile": "process definition",
    "Chart.yaml": "helm chart",
    "skaffold.yaml": "build pipeline",
    "serverless.yml": "serverless stack",
    "vercel.json": "hosting",
    "netlify.toml": "hosting",
    "fly.toml": "hosting",
    "render.yaml": "hosting",
}

_INFRA_SUFFIXES: dict[str, str] = {".tf": "terraform", ".tfvars": "terraform", ".bicep": "bicep"}

#: A Dockerfile with a suffix or prefix — `Dockerfile.prod`, `prod.Dockerfile`.
_DOCKERFILE = re.compile(r"^Dockerfile(\..+)?$|^.+\.Dockerfile$")

#: Directories whose YAML is deployment rather than configuration.
_INFRA_DIRS = frozenset({"k8s", "kubernetes", "manifests", "deploy", "deployment", "charts", "helm"})

#: CI definitions live at known paths and are worth naming as infrastructure.
_CI_DIRS = frozenset({".github/workflows", ".gitlab-ci", ".circleci", ".buildkite"})

_TEST_DIR_NAMES = frozenset({"tests", "test", "testing", "spec", "specs", "__tests__", "e2e"})


def scan_repository(root, max_depth: int = 4) -> list[str]:
    """
    Repository-relative paths worth classifying.

    Needed because `ParsedCodebase` only carries files whose extension maps to a
    language — `docker-compose.yml`, `Dockerfile` and `.env.example` are never in it,
    so detection driven off parsed files alone finds no infrastructure at all.

    Bounded in depth: past a few levels, a compose file belongs to a vendored example
    rather than to this project.
    """
    from pathlib import Path

    base = Path(root)
    if not base.is_dir():
        return []

    out: list[str] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if relative.count("/") >= max_depth or registry.should_skip(relative):
            continue
        out.append(relative)
    return sorted(out)


def detect_file_entities(paths: list[str]) -> list[dict]:
    """
    Config, infrastructure and test-suite entities.

    Purely path-based — every rule here keys on a filename, a suffix or a directory,
    so no file content is read. Returns rows in the shape `build_modules` produces,
    so the extractor merges them without special-casing.
    """
    out: list[dict] = []
    test_roots: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    for relative in paths:
        path = PurePosixPath(relative)
        name = path.name

        if (purpose := _CONFIG_FILES.get(name)) and (str(EntityKind.CONFIG_FILE), relative) not in seen:
            seen.add((str(EntityKind.CONFIG_FILE), relative))
            out.append(_row(EntityKind.CONFIG_FILE, name, relative, {"purpose": purpose}))

        if (infra := _infra_kind(relative, path, name)) and (str(EntityKind.INFRA_RESOURCE), relative) not in seen:
            seen.add((str(EntityKind.INFRA_RESOURCE), relative))
            out.append(_row(EntityKind.INFRA_RESOURCE, name, relative, {"type": infra}))

        # The suite is the directory, not each file: a repository with 400 test files
        # has a handful of suites, and 400 entities would drown everything else.
        if root := _test_root(path):
            test_roots[root] = test_roots.get(root, 0) + 1

    for root, count in sorted(test_roots.items()):
        out.append(_row(EntityKind.TEST_SUITE, root, root, {"files": count}))

    return out


def _infra_kind(relative_path: str, path: PurePosixPath, name: str) -> str | None:
    if kind := _INFRA_FILES.get(name):
        return kind
    if _DOCKERFILE.match(name):
        return "container image"
    if kind := _INFRA_SUFFIXES.get(path.suffix.lower()):
        return kind
    parent = path.parent.as_posix()
    if any(parent == d or parent.startswith(f"{d}/") for d in _CI_DIRS):
        return "ci pipeline"
    if path.suffix.lower() in (".yml", ".yaml") and any(p in _INFRA_DIRS for p in path.parts[:-1]):
        return "deployment manifest"
    return None


def _test_root(path: PurePosixPath) -> str | None:
    """The outermost directory that names a test suite, or None."""
    parts = path.parts[:-1]
    for index, part in enumerate(parts):
        if part.lower() in _TEST_DIR_NAMES:
            return "/".join(parts[: index + 1])
    return None


def _row(kind: str, name: str, path: str, data: dict) -> dict:
    return {
        "kind": str(kind),
        "name": name,
        "data_json": data,
        "source_path": path,
        "source_line": None,
    }


__all__ = ["detect_file_entities", "scan_repository"]
