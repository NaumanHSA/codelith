"""
The codebase as a map: every file, what kind of thing it is, where it belongs, and
what it imports.

The studio's atlas draws this, and its complaint about the old graph was the right
one: roles are assigned per *module*, most modules are services, so a map coloured by
role is one colour. Neurosurfer has 355 files and 224 of them carry the role
`service`. Which file is the HTTP surface, which one opens the database, which ones are
tests: that is what a reader looks for, and analysis already knows it file by file,
because the facts it extracted carry a source path.

So a file's kind is read from what analysis stored, in this order, and nothing is
derived that analysis did not already establish:

1. a test, by the module flag or the language provider's own rule;
2. an entry point, a route, a command or a datastore *declared in this file*, from
   the facts;
3. the module's role, when the role says more than "service";
4. the file's own name, for the three kinds every ecosystem names alike:
   configuration, data shapes and helpers. Compared on the stem, never on an extension, so the rule is the
   same in every language;
5. otherwise a service.

Files are grouped by the components the architecture pass named for this codebase
(`knowledge/services.py`). The files it never placed are given a home from the code
itself (`place_files`): tests with the tests, files for running the code in *Build &
run*, the rest by their folder or their imports, and each node says why it is where it
is. Configuration files, datastores and outside services are
facts rather than parsed files; each becomes a node of its own, linked from the file
that declares it, so the map can show what the code talks to.

**No model call, no re-reading.** Four queries against the knowledge base. The
shortest-path tree the atlas draws on selection is computed in the browser from these
same edges; `/preflight` stays the authority for counts, tests and cited pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.constants import EntityKind, ModuleRole
from codelith.knowledge.detectors import project_file_kind
from codelith.knowledge.services import HOUSE_PARTS, OTHER, assign, components, place_files
from codelith.languages import registry
from codelith.models.graph import GraphCall, GraphFile, GraphImport, GraphSymbol
from codelith.models.knowledge import KBEntity, KBModule, KnowledgeBase

#: The vocabulary the studio draws, one icon and one colour each. Thirteen, not the
#: twelve module roles: a role says what a *module* is for, a kind what a *file* is.
FILE_KINDS: tuple[str, ...] = (
    "service",
    "api",
    "data",
    "store",
    "model",
    "config",
    "env",
    "test",
    "cli",
    "entry",
    "util",
    "ui",
    "external",
    # Project files: what it takes to install, configure and run the code.
    "manifest",
    "lockfile",
    "deploy",
    "ci",
    "tooling",
    "docs",
)

#: A role that already says more than "service" decides the kind outright.
_ROLE_KIND: dict[str, str] = {
    ModuleRole.API: "api",
    ModuleRole.DATA_ACCESS: "data",
    ModuleRole.MODEL: "model",
    ModuleRole.SCHEMA: "model",
    ModuleRole.CONFIG: "config",
    ModuleRole.INFRA: "config",
    ModuleRole.CLI: "cli",
    ModuleRole.UTILITY: "util",
    ModuleRole.UI: "ui",
    ModuleRole.TEST: "test",
}

#: File stems that mean the same thing in every ecosystem. Matched on the stem with no
#: extension, so `settings.py`, `settings.ts` and `config.go` read alike.
_CONFIG_STEMS = frozenset({"config", "configs", "configuration", "settings", "constants", "conf"})
_MODEL_STEMS = frozenset({"models", "model", "schema", "schemas", "types", "entities", "dto", "dtos"})
_MODEL_DIRS = frozenset({"models", "schemas", "entities"})
_UTIL_STEMS = frozenset({"utils", "util", "helpers", "helper", "common", "misc"})
_UTIL_DIRS = frozenset({"utils", "util", "helpers"})

#: Facts drawn as nodes of their own, and the kind each becomes.
_FACT_NODES: dict[str, str] = {
    EntityKind.CONFIG_FILE: "config",
    EntityKind.DATASTORE: "store",
    EntityKind.EXTERNAL_API: "external",
}

#: Facts that settle a file's kind when the file declares one, strongest first.
_DECLARES: tuple[tuple[str, str], ...] = (
    (EntityKind.ENTRYPOINT, "entry"),
    (EntityKind.ROUTE, "api"),
    (EntityKind.CLI_COMMAND, "cli"),
    (EntityKind.DATASTORE, "data"),
)

#: The part for files nothing ties to a named one. Kept under this name for the
#: callers that leave it out of what they say about parts.
UNMAPPED = OTHER
CONFIGURATION = "Configuration"
OUTSIDE = "Outside world"

#: Rows per direction in a file's call listing. A file is rarely called from more
#: places than this, and one that is has made its point.
_CALL_CAP = 200


def file_kind(path: str, role: str | None, is_test: bool, declares: set[str]) -> str:
    """
    What kind of file this is, from what analysis stored about it.

    `declares` is the set of fact kinds whose source is this file. Pure, so the order
    of the rules is pinned by tests rather than by a query.

    A project file (a manifest, an env file, a Dockerfile, a CI workflow) is that
    first; source code never is one.
    """
    if (project := project_file_kind(path)) is not None:
        return project
    if is_test or role == ModuleRole.TEST or _provider_says_test(path):
        return "test"
    for fact, kind in _DECLARES:
        if fact in declares:
            return kind
    if role in _ROLE_KIND:
        return _ROLE_KIND[role]

    pure = PurePosixPath(path.lower())
    stem = pure.stem.lstrip("._")
    if stem in _CONFIG_STEMS or stem.endswith(("_config", "-config", ".config")):
        return "config"
    if stem in _MODEL_STEMS or any(part in _MODEL_DIRS for part in pure.parts[:-1]):
        return "model"
    if stem in _UTIL_STEMS or stem.endswith(("_utils", "_helpers")) or any(
        part in _UTIL_DIRS for part in pure.parts[:-1]
    ):
        return "util"
    return "service"


def fact_kind(entity_kind: str, name: str) -> str:
    """The kind a fact node takes. An environment file is not a config manifest."""
    kind = _FACT_NODES.get(entity_kind, "config")
    if kind == "config" and ".env" in name.lower():
        return "env"
    return kind


def _provider_says_test(path: str) -> bool:
    provider = registry.for_path(path)
    return bool(provider and provider.is_test_file(path))


@dataclass(slots=True)
class AtlasComponent:
    name: str
    description: str
    #: `component` for one analysis named; `tests`, `scripts`, `setup` or `other` for
    #: one made here; `config` or `outside` for the fact groups.
    group: str


@dataclass(slots=True)
class AtlasNode:
    id: str
    #: A repository path for a file; the fact's name for a fact node.
    path: str
    kind: str
    component: int
    loc: int = 0
    language: str | None = None
    symbols: int = 0
    #: The entity kind, for a node that is a fact rather than a file.
    fact: str | None = None
    #: What a fact node is: a datastore's engine, an outside service's client or URL.
    detail: str | None = None
    #: The file that declares a fact node.
    source: str | None = None
    #: Why a file is in its part, in one sentence.
    why: str | None = None


@dataclass(slots=True)
class Atlas:
    commit: str | None
    components: list[AtlasComponent] = field(default_factory=list)
    nodes: list[AtlasNode] = field(default_factory=list)
    #: `(importer, imported)` as node indexes, and fact links as `(file, fact)`.
    edges: list[tuple[int, int]] = field(default_factory=list)

    @property
    def kinds(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for node in self.nodes:
            out[node.kind] = out.get(node.kind, 0) + 1
        return out


class AtlasService:
    """Builds the map for one knowledge base."""

    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb

    async def build(self) -> Atlas:
        kb = self.kb
        atlas = Atlas(commit=kb.commit_sha)

        modules = (
            await self.db.execute(
                select(KBModule.path, KBModule.name, KBModule.role, KBModule.is_test).where(
                    KBModule.kb_id == kb.id
                )
            )
        ).all()
        by_key = {path: (name, role, bool(is_test)) for path, name, role, is_test in modules}
        module_why: dict[str, str] = {}
        owner = assign(kb.architecture_json, [name for name, _, _ in by_key.values()], module_why)

        facts = (
            await self.db.execute(
                select(KBEntity.kind, KBEntity.name, KBEntity.source_path, KBEntity.data_json).where(
                    KBEntity.kb_id == kb.id
                )
            )
        ).all()
        declares: dict[str, set[str]] = {}
        for kind, _, source, _ in facts:
            if source:
                declares.setdefault(source, set()).add(kind)

        symbol_counts = dict(
            (
                await self.db.execute(
                    select(GraphSymbol.path, func.count())
                    .where(GraphSymbol.project_id == kb.project_id, GraphSymbol.kb_id == kb.id)
                    .group_by(GraphSymbol.path)
                )
            ).all()
        )

        # Components in the order analysis listed them, then the groups made here.
        component_ix: dict[str, int] = {}

        def component(name: str, description: str, group: str) -> int:
            if name not in component_ix:
                component_ix[name] = len(atlas.components)
                atlas.components.append(AtlasComponent(name, description, group))
            return component_ix[name]

        for item in _named_components(kb.architecture_json):
            component(item[0], item[1], "component")

        files = (
            await self.db.execute(
                select(GraphFile.path, GraphFile.module_key, GraphFile.loc, GraphFile.language)
                .where(GraphFile.project_id == kb.project_id, GraphFile.kb_id == kb.id)
                .order_by(GraphFile.path)
            )
        ).all()
        rows: list[tuple[str, int, str | None]] = []
        named: dict[str, str | None] = {}
        kinds: dict[str, str] = {}
        why: dict[str, str] = {}
        for path, module_key, loc, language in files:
            if path in named:
                continue
            name, role, is_test = by_key.get(module_key or "", ("", None, False))
            home = owner.get(name)
            named[path] = home if home in component_ix else None
            if named[path] and name in module_why:
                why[path] = module_why[name]
            kinds[path] = file_kind(path, role, is_test, declares.get(path, set()))
            rows.append((path, int(loc or 0), language))

        imports = (
            await self.db.execute(
                select(GraphImport.src, GraphImport.dst).where(
                    GraphImport.project_id == kb.project_id, GraphImport.kb_id == kb.id
                )
            )
        ).all()
        placed = place_files(named, kinds, [(src, dst) for src, dst in imports], why)
        # The parts made here come after the named ones, always in the same order.
        for group, (name, description) in HOUSE_PARTS.items():
            if any(p.group == group for p in placed.values()):
                component(name, description, group)

        index: dict[str, int] = {}
        for path, loc, language in rows:
            where = placed[path]
            index[path] = len(atlas.nodes)
            atlas.nodes.append(
                AtlasNode(
                    id=path,
                    path=path,
                    kind=kinds[path],
                    component=component(where.part, "", where.group),
                    loc=loc,
                    language=language,
                    symbols=int(symbol_counts.get(path, 0)),
                    why=where.reason,
                )
            )

        edges: set[tuple[int, int]] = set()
        for src, dst in imports:
            a, b = index.get(src), index.get(dst)
            if a is not None and b is not None and a != b:
                edges.add((a, b))

        for kind, name, source, data in facts:
            if kind not in _FACT_NODES:
                continue
            # A configuration file the reading kept is a file on the map already.
            if kind == EntityKind.CONFIG_FILE and source in index:
                continue
            node_id = f"@{kind}:{name}"
            if node_id in index:
                if source in index:
                    edges.add((index[source], index[node_id]))
                continue
            if kind == EntityKind.CONFIG_FILE:
                ci = component(
                    CONFIGURATION,
                    "Manifests and environment files the code is configured from.",
                    "config",
                )
            else:
                ci = component(
                    OUTSIDE, "Datastores and third-party services the code talks to.", "outside"
                )
            index[node_id] = len(atlas.nodes)
            atlas.nodes.append(
                AtlasNode(
                    id=node_id,
                    path=name,
                    kind=fact_kind(kind, name),
                    component=ci,
                    fact=kind,
                    detail=_detail(data),
                    source=source,
                )
            )
            if source in index:
                edges.add((index[source], index[node_id]))

        atlas.edges = sorted(edges)
        return atlas

    async def calls(self, path: str) -> dict:
        """
        One file from the inside: what it declares, what it calls elsewhere, and what
        calls into it. The atlas's deepest zoom, fetched only for the file in view.
        """
        kb = self.kb
        scope = (GraphCall.project_id == kb.project_id, GraphCall.kb_id == kb.id)

        symbols = (
            await self.db.execute(
                select(
                    GraphSymbol.name,
                    GraphSymbol.qname,
                    GraphSymbol.kind,
                    GraphSymbol.line,
                    GraphSymbol.end_line,
                )
                .where(
                    GraphSymbol.project_id == kb.project_id,
                    GraphSymbol.kb_id == kb.id,
                    GraphSymbol.path == path,
                )
                .order_by(GraphSymbol.line, GraphSymbol.qname)
            )
        ).all()

        rows = (
            await self.db.execute(
                select(
                    GraphCall.src_path, GraphCall.src_qname, GraphCall.dst_path, GraphCall.dst_qname
                )
                .where(*scope, or_(GraphCall.src_path == path, GraphCall.dst_path == path))
                .distinct()
                .order_by(GraphCall.src_path, GraphCall.src_qname, GraphCall.dst_qname)
            )
        ).all()

        outgoing, incoming = [], []
        for src_path, src_q, dst_path, dst_q in rows:
            if src_path == path and dst_path != path and len(outgoing) < _CALL_CAP:
                outgoing.append({"caller": src_q, "path": dst_path, "callee": dst_q})
            elif dst_path == path and src_path != path and len(incoming) < _CALL_CAP:
                incoming.append({"caller": src_q, "path": src_path, "callee": dst_q})

        return {
            "path": path,
            # Fields, variables and constants are what a file holds, not what it does;
            # an outline of 40 fields hides the six functions a reader came for.
            "symbols": [
                {"name": n, "qname": q, "kind": k, "line": ln, "end_line": end}
                for n, q, k, ln, end in symbols
                if k in ("class", "function", "method", "constructor", "property", "interface", "type")
            ],
            "outgoing": outgoing,
            "incoming": incoming,
        }


def _named_components(architecture: object) -> list[tuple[str, str]]:
    return [(c.name, c.description) for c in components(architecture)]


def _detail(data: object) -> str | None:
    """One line saying what a fact node is, from its stored payload."""
    if not isinstance(data, dict):
        return None
    for key in ("engine", "client", "via", "purpose"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "Atlas",
    "AtlasComponent",
    "AtlasNode",
    "AtlasService",
    "CONFIGURATION",
    "FILE_KINDS",
    "OUTSIDE",
    "UNMAPPED",
    "fact_kind",
    "file_kind",
]
