"""
How to run it: what the code needs, how to install it, run it and test it, and the
environment it expects. Assembled from the files a reading keeps, never written by a
model.

The first thing anyone does with a codebase they did not write is try to run it, and
the answer is scattered across five files that each say part of it: the manifest
names the runtime and the dependencies, the lockfile the package manager, the Makefile
the commands people actually type, the compose file the database it expects, the env
template the settings, and the CI workflow what is really run to test it. Each is
read here for its part; the language-specific ones through their provider
(`LanguageProvider.run_info`), the rest, which are the same in every language, here.

The same block is shown on the codebase page, handed to agents (`how_to("run")` and the
instruction file), and followed by QA when it installs and tests the code in a sandbox.
So it says only what a file says, and names the file.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.source_repo import SourceRepository, StoredFile
from codelith.knowledge.constants import EntityKind
from codelith.knowledge.detectors import MASK
from codelith.languages import registry
from codelith.models.knowledge import KBEntity, KnowledgeBase

logger = structlog.get_logger(__name__)

#: Services a compose file runs, by the image they come from, and what to call them.
_SERVICES: tuple[tuple[str, str], ...] = (
    ("postgres", "PostgreSQL"),
    ("postgis", "PostgreSQL"),
    ("timescale", "PostgreSQL"),
    ("mysql", "MySQL"),
    ("mariadb", "MariaDB"),
    ("redis", "Redis"),
    ("valkey", "Valkey"),
    ("mongo", "MongoDB"),
    ("rabbitmq", "RabbitMQ"),
    ("elasticsearch", "Elasticsearch"),
    ("opensearch", "OpenSearch"),
    ("minio", "MinIO"),
    ("kafka", "Kafka"),
    ("neo4j", "Neo4j"),
    ("qdrant", "Qdrant"),
    ("chroma", "Chroma"),
    ("ollama", "Ollama"),
    ("memcached", "Memcached"),
    ("localstack", "LocalStack"),
    ("mailhog", "MailHog"),
    ("mailpit", "Mailpit"),
    ("nats", "NATS"),
    ("clickhouse", "ClickHouse"),
)

#: Make and just targets, by what they are for. The bare word sorts before its
#: variants (`test` before `test-unit`).
_INSTALL_TARGETS = re.compile(r"^(install|setup|bootstrap|deps|dependencies|init|venv)([-_:].*)?$")
_RUN_TARGETS = re.compile(r"^(dev|run|start|serve|server|watch)([-_:].*)?$")
_TEST_TARGETS = re.compile(r"^(test|tests|check)([-_:].*)?$")
_CONTAINER_TARGETS = re.compile(r"^(docker|compose|up)([-_:](up|run|start|build))?$")

#: A make target line: `name: deps ## what it does`. Not `X := value`.
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?![=:])([^#]*)(?:##\s*(.*))?$")
_JUST_RECIPE = re.compile(r"^@?([A-Za-z][\w-]*)(?:\s+[^:=]*)?:(?!=)")
_ENV_ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

#: Names that are secrets whatever the codebase: kept out of git, never echoed.
_SECRET = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|PRIVATE|DSN|AUTH)", re.IGNORECASE)

#: Commands in a CI workflow worth repeating: the ones that install, build or test.
_CI_COMMAND = re.compile(
    r"^(pip|pip3|python|python3|uv|poetry|pytest|tox|nox|make|just|npm|pnpm|yarn|bun|npx|node|go|mvn|\./mvnw|gradle|\./gradlew|cargo|ruff|mypy|tsc|docker|alembic)\b"
)

#: Pins a runtime version, with what it pins.
_VERSION_FILES = {".python-version": "Python", "runtime.txt": "Python", ".nvmrc": "Node.js", ".node-version": "Node.js"}


@dataclass(slots=True)
class Need:
    """Something that has to be there before the code runs."""

    what: str
    version: str | None
    source: str
    #: `runtime` or `service`.
    kind: str


@dataclass(slots=True)
class Step:
    command: str
    note: str
    source: str
    #: Where it sorts: root folder first, the target people type before what a
    #: manifest implies, the main language's manifest before the rest.
    order: tuple = field(default=(), compare=False, repr=False)


@dataclass(slots=True)
class EnvNeed:
    name: str
    declared_in: list[str] = field(default_factory=list)
    read_in: list[str] = field(default_factory=list)
    #: A template, the compose file or the Dockerfile gives it a value.
    has_default: bool = False
    secret: bool = False
    #: The code fails without it (True), copes or has a default (False), or the
    #: language does not say (None).
    required: bool | None = None

    @property
    def missing(self) -> bool:
        """The code needs it, and no template, compose file or Dockerfile declares it."""
        return bool(self.read_in) and not self.declared_in and self.required is True

    @property
    def undocumented(self) -> bool:
        """Read by the code and declared nowhere, but the code has a default or copes."""
        return bool(self.read_in) and not self.declared_in and self.required is not True


@dataclass(slots=True)
class Runbook:
    available: bool = False
    reason: str = ""
    commit: str | None = None
    needs: list[Need] = field(default_factory=list)
    install: list[Step] = field(default_factory=list)
    run: list[Step] = field(default_factory=list)
    test: list[Step] = field(default_factory=list)
    container: list[Step] = field(default_factory=list)
    #: What the CI workflows run: the closest thing to proof of how it is tested.
    ci: list[Step] = field(default_factory=list)
    env: list[EnvNeed] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.needs or self.install or self.run or self.test or self.container or self.env)

    def markdown(self, heading: str = "## How to run it") -> str:
        out = [heading, ""]
        if not self.available:
            return "\n".join([*out, self.reason, ""])
        if self.needs:
            out.append(
                "**Needs:** "
                + " · ".join(f"{n.what}{' ' + n.version if n.version else ''} (`{n.source}`)" for n in self.needs)
            )
            out.append("")
        for title, steps in (
            ("Install", self.install),
            ("Run", self.run),
            ("Test", self.test),
            ("In a container", self.container),
        ):
            if steps:
                out += [f"**{title}**", ""]
                out += [
                    f"- `{s.command}`" + (f": {s.note}" if s.note else "") + f" (`{s.source}`)" for s in steps[:6]
                ]
                if len(steps) > 6:
                    out.append(f"- and {len(steps) - 6} more")
                out.append("")
        if self.ci:
            out.append("**CI runs:** " + ", ".join(f"`{s.command}`" for s in self.ci[:8]))
            out.append("")
        missing = [e for e in self.env if e.missing]
        declared = [e for e in self.env if e.declared_in]
        if declared or any(e.read_in for e in self.env):
            out += ["**Environment**", ""]
            if declared:
                required = [e.name for e in declared if not e.has_default]
                out.append(
                    f"- {len(declared)} variable(s) declared in "
                    + ", ".join(f"`{p}`" for p in sorted({p for e in declared for p in e.declared_in})[:4])
                    + (f"; without a default: {', '.join(f'`{n}`' for n in required[:12])}" if required else "")
                )
            if missing:
                out.append(
                    "- Needed by the code and declared nowhere: " + ", ".join(f"`{e.name}`" for e in missing[:12])
                )
            undocumented = [e for e in self.env if e.undocumented]
            if undocumented:
                out.append(
                    f"- Read by the code, in no template ({len(undocumented)}): "
                    + ", ".join(f"`{e.name}`" for e in undocumented[:10])
                    + (" …" if len(undocumented) > 10 else "")
                )
            out.append("")
        return "\n".join(out)


def _folder(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def _in(folder: str, command: str) -> str:
    return f"cd {folder} && {command}" if folder else command


def _add(steps: list[Step], step: Step) -> None:
    if all(s.command != step.command for s in steps):
        steps.append(step)


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def make_targets(text: str) -> list[tuple[str, str]]:
    """
    `(target, description)` for each target a Makefile defines, in file order. The
    description is the `## ...` on the line, or a one-line comment right above it; a
    longer comment block above is about more than the target, and is not used.
    """
    out: list[tuple[str, str]] = []
    above = ""
    block = 0
    for line in text.splitlines():
        if line.startswith("#"):
            block += 1
            above = line.lstrip("# ").strip() if block == 1 else ""
            continue
        block = 0
        match = _MAKE_TARGET.match(line)
        if match and not line.startswith((" ", "\t")):
            target = match.group(1)
            if not target.startswith(".") and "%" not in target and "$" not in target:
                out.append((target, (match.group(3) or above or "").strip()))
        above = ""
    seen: set[str] = set()
    return [(t, d) for t, d in out if not (t in seen or seen.add(t))]


def just_recipes(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    above = ""
    block = 0
    for line in text.splitlines():
        if line.startswith("#"):
            block += 1
            above = line.lstrip("# ").strip() if block == 1 else ""
            continue
        block = 0
        if not line.startswith((" ", "\t")) and (match := _JUST_RECIPE.match(line)):
            out.append((match.group(1), above))
        above = ""
    return out


def env_template(text: str) -> dict[str, bool]:
    """Name to whether the template gives it a value."""
    out: dict[str, bool] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if match := _ENV_ASSIGN.match(line):
            value = match.group(2).split(" #", 1)[0].strip().strip("'\"")
            out[match.group(1)] = bool(value) and value != MASK
    return out


def _load_yaml(text: str) -> object:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _service_name(image: str) -> str | None:
    base = image.lower().rsplit("/", 1)[-1].split(":", 1)[0]
    for needle, name in _SERVICES:
        if needle in base:
            return name
    return None


def ci_commands(text: str) -> list[str]:
    """The install, build and test commands a CI workflow runs."""
    data = _load_yaml(text)
    found: list[str] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("run", "script") and isinstance(value, (str, list)):
                    lines = value.splitlines() if isinstance(value, str) else [str(v) for v in value]
                    for line in lines:
                        line = line.strip()
                        if line and _CI_COMMAND.match(line) and line not in found:
                            found.append(line[:160])
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(data)
    return found


class RunbookService:
    """`build()` the runbook for one reading."""

    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb

    async def build(self) -> Runbook:
        kb = self.kb
        book = Runbook(commit=kb.commit_sha)
        sources = SourceRepository(self.db)
        kept = await sources.files(kb.id, project_only=True)
        if not kept and not await sources.has_snapshot(kb.id):
            book.reason = (
                "This reading was taken before Codelith kept each reading's files. "
                "Read the codebase again to see how to run it."
            )
            return book
        book.available = True

        siblings: dict[str, set[str]] = defaultdict(set)
        for f in kept:
            siblings[_folder(f.path)].add(PurePosixPath(f.path).name)
        # Root first, then by depth, so the commands a newcomer types first come first.
        ordered = sorted(kept, key=lambda f: (f.path.count("/"), f.path))
        texts: dict[str, str] = {}
        for f in ordered:
            if f.kind != "lockfile":
                texts[f.path] = await sources.text(f.hash) or ""

        # The codebase's main language leads: its manifest's commands come first.
        share: dict[str, int] = defaultdict(int)
        for f in await sources.files(kb.id):
            if f.kind is None and f.language:
                share[f.language] += 1
        self._share = share

        provided: dict[str, list[str]] = defaultdict(list)
        defaults: dict[str, bool] = {}
        runtimes: dict[str, Need] = {}
        # After compose files, so a Dockerfile a compose file builds is not offered twice.
        dockerfiles: list[StoredFile] = []

        for f in ordered:
            name, folder = PurePosixPath(f.path).name, _folder(f.path)
            text = texts.get(f.path, "")
            try:
                if f.kind == "manifest":
                    self._manifest(book, f, text, frozenset(siblings[folder]), runtimes)
                elif name in _VERSION_FILES and text.strip():
                    what = _VERSION_FILES[name]
                    version = text.strip().splitlines()[0].replace("python-", "")
                    need = runtimes.get(what)
                    if need is None or not need.version:
                        runtimes[what] = Need(what, version, f.path, "runtime")
                elif name in ("Makefile", "makefile", "GNUmakefile"):
                    self._targets(book, f.path, folder, [(f"make {t}", t, d) for t, d in make_targets(text)])
                elif name in ("justfile", "Justfile"):
                    self._targets(book, f.path, folder, [(f"just {t}", t, d) for t, d in just_recipes(text)])
                elif f.kind == "env":
                    for var, has_value in env_template(text).items():
                        provided[var].append(f.path)
                        defaults[var] = defaults.get(var, False) or has_value
                elif f.kind == "deploy" and name.lower().startswith(("docker-compose", "compose")):
                    self._compose(book, f.path, folder, text, provided, defaults)
                elif f.kind == "deploy" and "dockerfile" in name.lower() and name != ".dockerignore":
                    dockerfiles.append(f)
                elif f.kind == "ci":
                    for command in ci_commands(text):
                        _add(book.ci, Step(command, "", f.path))
            except Exception as exc:  # a malformed file says nothing; it must not end the runbook
                logger.info("runbook_file_skipped", path=f.path, error=f"{type(exc).__name__}: {exc}")

        for f in dockerfiles:
            self._dockerfile(book, f.path, _folder(f.path), texts.get(f.path, ""), provided, defaults)
        for steps in (book.install, book.run, book.test, book.container):
            steps.sort(key=lambda s: s.order)
        book.needs = sorted(runtimes.values(), key=lambda n: -self._weight(n.what)) + book.needs

        await self._env(book, provided, defaults)
        await self._datastores(book)
        return book

    _RUNTIME_LANGUAGE = {"Python": "python", "Node.js": "typescript", "Go": "go", "Java": "java"}

    def _weight(self, runtime: str) -> int:
        language = self._RUNTIME_LANGUAGE.get(runtime, "")
        weight = self._share.get(language, 0)
        return weight + (self._share.get("javascript", 0) if runtime == "Node.js" else 0)

    def _manifest(
        self, book: Runbook, f: StoredFile, text: str, siblings: frozenset[str], runtimes: dict[str, Need]
    ) -> None:
        folder = _folder(f.path)
        depth = folder.count("/") + 1 if folder else 0
        for provider in registry.manifest_providers(f.path):
            info = provider.run_info(f.path, text, siblings)
            if info is None:
                continue
            if info.runtime and (info.runtime not in runtimes or not runtimes[info.runtime].version):
                runtimes[info.runtime] = Need(info.runtime, info.version, f.path, "runtime")
            rank = -self._weight(info.runtime or "")
            for i, command in enumerate(info.install):
                _add(book.install, Step(_in(folder, command), "", f.path, (depth, 1, rank, f.path, i)))
            for i, (command, note) in enumerate(info.run):
                _add(book.run, Step(_in(folder, command), note, f.path, (depth, 1, rank, f.path, i)))
            for i, command in enumerate(info.test):
                _add(book.test, Step(_in(folder, command), "", f.path, (depth, 1, rank, f.path, i)))

    @staticmethod
    def _targets(book: Runbook, source: str, folder: str, targets: list[tuple[str, str, str]]) -> None:
        """Make or just targets. The ones people type come before what a manifest implies."""
        depth = folder.count("/") + 1 if folder else 0
        for i, (command, target, note) in enumerate(targets):
            for pattern, steps in (
                (_INSTALL_TARGETS, book.install),
                (_TEST_TARGETS, book.test),
                (_RUN_TARGETS, book.run),
                (_CONTAINER_TARGETS, book.container),
            ):
                if match := pattern.match(target):
                    variant = 0 if not match.group(2) else 1
                    _add(steps, Step(_in(folder, command), note, source, (depth, 0, variant, source, i)))
                    break

    @staticmethod
    def _compose(
        book: Runbook, source: str, folder: str, text: str, provided: dict[str, list[str]], defaults: dict[str, bool]
    ) -> None:
        data = _load_yaml(text)
        services = data.get("services") if isinstance(data, dict) else None
        if not isinstance(services, dict):
            return
        builds = False
        for service in services.values():
            if not isinstance(service, dict):
                continue
            image = str(service.get("image") or "")
            builds = builds or "build" in service
            known = _service_name(image) if image else None
            if known and all(n.what != known for n in book.needs):
                tag = image.split(":", 1)[1] if ":" in image else None
                book.needs.append(Need(known, tag, source, "service"))
            env = service.get("environment")
            pairs = (
                [(str(k), v is not None and str(v) != "") for k, v in env.items()]
                if isinstance(env, dict)
                else [(str(e).split("=", 1)[0], "=" in str(e) and bool(str(e).split("=", 1)[1])) for e in env or []]
            )
            for var, has_value in pairs:
                if _IDENT.match(var):
                    provided[var].append(source)
                    defaults[var] = defaults.get(var, False) or has_value
        depth = folder.count("/") + 1 if folder else 0
        _add(
            book.container,
            Step(_in(folder, "docker compose up"), "starts " + ", ".join(list(services)[:5]), source, (depth, 1, 0, source, 0)),
        )
        if builds:
            _add(
                book.container,
                Step(_in(folder, "docker compose up --build"), "after a change to the code", source, (depth, 1, 0, source, 1)),
            )

    @staticmethod
    def _dockerfile(
        book: Runbook, source: str, folder: str, text: str, provided: dict[str, list[str]], defaults: dict[str, bool]
    ) -> None:
        base = ""
        ports: list[str] = []
        # Continuation lines joined, so `ENV A=1 \` and the next line read as one.
        for line in re.sub(r"\\\s*\n", " ", text).splitlines():
            words = line.strip().split()
            if not words:
                continue
            op = words[0].upper()
            if op == "FROM" and len(words) > 1:
                base = words[1]
            elif op == "EXPOSE":
                ports += [w.split("/", 1)[0] for w in words[1:]]
            elif op == "ENV" and len(words) > 1:
                # `ENV A=1 B=2`, or the old `ENV A 1`: either way the image sets a value.
                names = [w.split("=", 1)[0] for w in words[1:] if "=" in w] or [words[1]]
                for var in names:
                    if _IDENT.match(var):
                        provided[var].append(source)
                        defaults[var] = True
        if any(s.source.endswith(("compose.yml", "compose.yaml")) for s in book.container):
            return
        tag = PurePosixPath(folder or "app").name or "app"
        publish = f" -p {ports[0]}:{ports[0]}" if ports else ""
        dockerfile = PurePosixPath(source).name
        file_flag = f" -f {dockerfile}" if dockerfile != "Dockerfile" else ""
        _add(
            book.container,
            Step(
                _in(folder, f"docker build{file_flag} -t {tag} . && docker run --rm{publish} {tag}"),
                f"from {base}" if base else "",
                source,
                (folder.count("/") + 1 if folder else 0, 1, 1, source, 0),
            ),
        )

    async def _env(self, book: Runbook, provided: dict[str, list[str]], defaults: dict[str, bool]) -> None:
        rows = (
            await self.db.execute(
                select(KBEntity.name, KBEntity.source_path, KBEntity.data_json).where(
                    KBEntity.kb_id == self.kb.id, KBEntity.kind == str(EntityKind.ENV_VAR)
                )
            )
        ).all()
        read: dict[str, list[str]] = defaultdict(list)
        required: dict[str, bool | None] = {}
        for name, source, data in rows:
            if source and source not in read[name]:
                read[name].append(source)
            said = data.get("required") if isinstance(data, dict) else None
            if isinstance(said, bool):
                # Required anywhere means required: one read with no default is enough.
                required[name] = required.get(name) is True or said
        names = sorted(set(read) | set(provided))
        env = [
            EnvNeed(
                name=n,
                declared_in=sorted(set(provided.get(n, []))),
                read_in=read.get(n, [])[:6],
                has_default=defaults.get(n, False),
                secret=bool(_SECRET.search(n)),
                required=required.get(n),
            )
            for n in names
        ]
        # What will stop it starting first: needed and declared nowhere; then declared
        # with no default; then read and in no template; the rest.
        env.sort(
            key=lambda e: (not e.missing, not (e.declared_in and not e.has_default), not e.undocumented, e.name)
        )
        book.env = env

    async def _datastores(self, book: Runbook) -> None:
        rows = (
            await self.db.execute(
                select(KBEntity.name, KBEntity.source_path).where(
                    KBEntity.kb_id == self.kb.id, KBEntity.kind == str(EntityKind.DATASTORE)
                )
            )
        ).all()
        for name, source in rows:
            known = _service_name(str(name))
            if known and all(n.what != known for n in book.needs):
                book.needs.append(Need(known, None, source or "", "service"))


__all__ = [
    "EnvNeed",
    "Need",
    "Runbook",
    "RunbookService",
    "Step",
    "ci_commands",
    "env_template",
    "just_recipes",
    "make_targets",
]
