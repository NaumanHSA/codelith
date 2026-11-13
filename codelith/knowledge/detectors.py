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
from dataclasses import dataclass
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


# -- Project files: what it takes to install, configure and run the code -------
#
# The code parser keeps only files a language owns by extension, so `pyproject.toml`,
# `.env.example`, a `Dockerfile` or a CI workflow were never files of a reading: their
# facts were pulled out, and the files themselves were gone. These are the files a
# person opens first when they want to run the code, and the ones a test run has to
# follow, so a reading keeps them, each with a kind:
#
#   manifest  dependencies and project metadata (each language provider names its own)
#   lockfile  the exact versions a manifest resolved to
#   env       environment files; a real one is kept with its values masked
#   deploy    containers, compose, Kubernetes, Terraform, hosting
#   ci        pipelines
#   tooling   build runners, tool settings, runtime pins
#   docs      the README and the guides on setting the project up

PROJECT_KINDS: tuple[str, ...] = ("manifest", "lockfile", "env", "deploy", "ci", "tooling", "docs")

#: Environment files that are templates, and safe to keep as written.
_ENV_TEMPLATES = frozenset({
    ".env.example", ".env.sample", ".env.template", ".env.dist", ".env.defaults",
    "env.example", "example.env", "sample.env", ".env.test.example",
})

#: Files whose values are secrets as often as not, kept with every value masked.
_SECRET_SETTINGS = frozenset({".npmrc", ".pypirc", ".netrc"})

_TOOLING_FILES = frozenset({
    "Makefile", "makefile", "GNUmakefile", "justfile", "Justfile", "Taskfile.yml",
    "Taskfile.yaml", "tox.ini", "pytest.ini", "alembic.ini", "mypy.ini", "ruff.toml",
    ".ruff.toml", ".pre-commit-config.yaml", ".editorconfig", ".python-version",
    ".nvmrc", ".node-version", ".tool-versions", "runtime.txt", ".prettierrc",
    ".prettierrc.json", ".eslintrc", ".eslintrc.json", ".eslintrc.yml", "jsconfig.json",
    "babel.config.json", "renovate.json", ".npmrc", ".pypirc", "nginx.conf",
    "golangci.yml", ".golangci.yml", "lombok.config", "gradle.properties",
    "dependabot.yml", "dependabot.yaml", "mkdocs.yml", "mkdocs.yaml",
    "mvnw", "gradlew", "settings.gradle", "settings.gradle.kts",
})

_DEPLOY_FILES = frozenset({
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    ".dockerignore", "Procfile", "Chart.yaml", "values.yaml", "skaffold.yaml",
    "serverless.yml", "vercel.json", "netlify.toml", "fly.toml", "render.yaml",
    "app.yaml", "Tiltfile",
})

_CI_FILES = frozenset({
    ".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", ".travis.yml",
    "bitbucket-pipelines.yml", "cloudbuild.yaml", "appveyor.yml",
})

#: Guides on setting a project up, kept from the root and one folder down; the rest of
#: a docs folder is documentation, which the markdown parser already reads.
_DOC_STEMS = ("readme", "contributing", "install", "setup", "development", "hacking")

#: Folders whose project files belong to fixtures and samples, not to this project.
_SAMPLE_DIRS = frozenset({"fixtures", "fixture", "testdata", "examples", "example", "samples", "sample"})

#: Read at most this much of a project file; a lockfile may be larger.
_MAX_BYTES = 256 * 1024
_MAX_LOCK_BYTES = 2 * 1024 * 1024

_ENV_LINE = re.compile(r"^(\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_.\-]*\s*[=:]\s*)(.*)$")

MASK = "\u2022\u2022\u2022"


@dataclass(frozen=True, slots=True)
class ProjectFile:
    """A project file as a reading keeps it."""

    path: str
    kind: str
    #: What to highlight it as: `toml`, `yaml`, `json`, `dockerfile`, `makefile`, ...
    language: str
    content: str
    #: True when the values were masked: the text is not what the file held.
    masked: bool = False


def in_sample_dir(relative: str) -> bool:
    """True for a file under a test, fixture or sample folder: not this project's own."""
    return any(f.lower() in _SAMPLE_DIRS or f.lower() in _TEST_DIR_NAMES for f in PurePosixPath(relative).parts[:-1])


def _is_real_env(name: str) -> bool:
    lowered = name.lower()
    if lowered in _ENV_TEMPLATES or lowered.endswith((".example", ".sample", ".template", ".dist")):
        return False
    return lowered == ".env" or lowered.startswith(".env.") or lowered.endswith(".env")


def project_file_kind(relative: str) -> str | None:
    """
    What kind of project file this is, or `None` when it is not one.

    Source code is never a project file, even `setup.py`: a language provider parses
    it, and it is a file of the reading already.
    """
    path = PurePosixPath(relative)
    name = path.name
    lowered = name.lower()
    folders = [p.lower() for p in path.parts[:-1]]
    if registry.for_path(relative) is not None or in_sample_dir(relative):
        return None

    for provider in registry.providers():
        if name in getattr(provider, "lock_files", ()):
            return "lockfile"
    if registry.manifest_providers(relative):
        return "manifest"
    if lowered in _ENV_TEMPLATES or _is_real_env(name):
        return "env"
    if _DOCKERFILE.match(name) or name in _DEPLOY_FILES or path.suffix.lower() in _INFRA_SUFFIXES:
        return "deploy"
    if path.suffix.lower() in (".yml", ".yaml") and any(f in _INFRA_DIRS for f in folders):
        return "deploy"
    parent = path.parent.as_posix()
    if name in _CI_FILES or (
        path.suffix.lower() in (".yml", ".yaml")
        and any(parent == d or parent.startswith(f"{d}/") for d in _CI_DIRS)
    ) or parent == ".circleci":
        return "ci"
    if name in _TOOLING_FILES or (lowered.startswith("tsconfig") and lowered.endswith(".json")):
        return "tooling"
    if path.suffix.lower() in (".md", ".rst", ".txt", "") and len(folders) <= 1 and lowered.startswith(_DOC_STEMS):
        return "docs"
    return None


def project_file_language(relative: str) -> str:
    """The language to highlight a project file as."""
    path = PurePosixPath(relative)
    name, suffix = path.name, path.suffix.lower()
    if _DOCKERFILE.match(name):
        return "dockerfile"
    if name in ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile"):
        return "makefile"
    if name in ("Pipfile", "poetry.lock", "uv.lock", "pdm.lock") or suffix == ".toml":
        return "toml"
    if suffix in (".yml", ".yaml") or name in ("pnpm-lock.yaml", "yarn.lock"):
        return "yaml"
    if suffix == ".json" or name in ("Pipfile.lock", ".prettierrc", ".eslintrc"):
        return "json"
    if suffix in (".ini", ".cfg", ".conf") or name in (".editorconfig", ".npmrc", ".pypirc", "gradle.properties"):
        return "ini"
    if suffix == ".xml":
        return "xml"
    if suffix == ".kts":
        return "kotlin"
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix in (".sh", ".bash") or name in ("mvnw", "gradlew"):
        return "bash"
    if ".env" in name.lower() or name.lower().endswith("env"):
        return "env"
    return "plaintext"


def mask_values(text: str) -> str:
    """Every `KEY=value` with its value replaced; names, comments and blanks kept."""
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        match = _ENV_LINE.match(body)
        if match and not body.lstrip().startswith("#") and match.group(2).strip():
            out.append(match.group(1) + MASK + ending)
        else:
            out.append(line)
    return "".join(out)


def read_project_files(root, max_depth: int = 4) -> list[ProjectFile]:
    """
    The project files under `root`, read, with a real environment file's values
    masked so they never reach the database.
    """
    from pathlib import Path

    base = Path(root)
    out: list[ProjectFile] = []
    for relative in scan_repository(root, max_depth=max_depth):
        kind = project_file_kind(relative)
        if kind is None:
            continue
        path = base / relative
        try:
            size = path.stat().st_size
            if size > (_MAX_LOCK_BYTES if kind == "lockfile" else _MAX_BYTES):
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        text = raw.decode("utf-8", errors="replace")
        name = PurePosixPath(relative).name
        masked = (kind == "env" and _is_real_env(name)) or name in _SECRET_SETTINGS
        if masked:
            text = mask_values(text)
        out.append(ProjectFile(relative, kind, project_file_language(relative), text, masked))
    return out


__all__ = [
    "MASK",
    "PROJECT_KINDS",
    "ProjectFile",
    "detect_file_entities",
    "in_sample_dir",
    "mask_values",
    "project_file_kind",
    "project_file_language",
    "read_project_files",
    "scan_repository",
]
