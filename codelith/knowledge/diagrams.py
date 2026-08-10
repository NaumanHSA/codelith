"""
Diagrams derived from the knowledge base.

Every function here turns facts we already hold — the import graph, the module
roles, the detected entities — into D2 source. **No model is called.** That is the
whole design: a diagram produced this way cannot contain a box that does not exist,
cannot invent an edge, and cannot emit invalid syntax, because none of those are
reachable from a builder that only accepts nodes and edges it was handed.

Where a model still has a job, it is choosing *what* to draw and writing the labels
— naming a subsystem, summarising a flow. Those are language tasks. Syntax is not.

Each function returns `None` when it has nothing worth drawing. A diagram of two
boxes and no edges is worse than no diagram: it takes up the space where an
explanation should be and tells the reader the system is trivial.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from codelith.knowledge.constants import EntityKind
from codelith.tools.d2 import (
    ident,
    SHAPE_PACKAGE,
    SHAPE_QUEUE,
    SHAPE_STORE,
    D2Diagram,
)

#: Below this an "architecture" diagram is a restatement of the file list.
_MIN_MODULES = 3
#: Above this it is a hairball nobody reads. The busiest modules are kept.
_MAX_MODULES = 14
_MAX_EDGES = 40

#: Roles that describe a layer, in the order a reader expects to meet them.
_ROLE_ORDER = (
    "api", "cli", "service", "worker", "data_access", "schema", "model",
    "config", "utility", "ui", "test",
)

_STORE_SHAPES = {
    "queue": SHAPE_QUEUE,
}


def module_map(graph_files: list[dict], imports: list[dict], roles: dict[str, str]) -> str | None:
    """
    Which modules depend on which, grouped by the role each plays.

    Built from `IMPORTS` edges aggregated to module level: a hundred file imports
    become a handful of module dependencies, which is the level a reader can hold in
    their head. The busiest modules survive the cap, since a module nothing imports
    is rarely what someone came to understand.
    """
    module_of = {f["path"]: f.get("module_key") for f in graph_files if f.get("module_key")}
    if len({m for m in module_of.values() if m}) < _MIN_MODULES:
        return None

    pairs: Counter[tuple[str, str]] = Counter()
    for edge in imports:
        source, target = module_of.get(edge["src"]), module_of.get(edge["dst"])
        if source and target and source != target:
            pairs[(source, target)] += 1

    if not pairs:
        return None

    degree: Counter[str] = Counter()
    for (source, target), weight in pairs.items():
        degree[source] += weight
        degree[target] += weight
    keep = {name for name, _ in degree.most_common(_MAX_MODULES)}

    diagram = D2Diagram(title="Module dependencies", direction="right")
    by_role: dict[str, list[str]] = defaultdict(list)
    for module in sorted(keep):
        by_role[roles.get(module, "unknown")].append(module)

    ordered = sorted(
        by_role.items(),
        key=lambda kv: (_ROLE_ORDER.index(kv[0]) if kv[0] in _ROLE_ORDER else len(_ROLE_ORDER)),
    )
    for role, modules in ordered:
        container = diagram.container(role.replace("_", " "))
        for module in modules:
            diagram.node(module, parent=container, key=module, tooltip=f"{role} module")

    for (source, target), weight in pairs.most_common(_MAX_EDGES):
        if source in keep and target in keep:
            diagram.edge(
                ident(source),
                ident(target),
                label="" if weight < 3 else f"{weight}",
            )

    return None if diagram.is_empty else diagram.render()


def system_context(entities: list[dict], project_name: str) -> str | None:
    """
    What this system talks to and what it stores in.

    The one diagram a reader wants before any other, and it needs no model at all:
    every box is an entity the extractor found, with a line and a file behind it.
    """
    datastores = _named(entities, EntityKind.DATASTORE)
    external = _named(entities, EntityKind.EXTERNAL_API)
    entrypoints = _named(entities, EntityKind.ENTRYPOINT)
    if not datastores and not external:
        return None

    diagram = D2Diagram(title=f"{project_name} — system context", direction="right")
    centre = diagram.node(project_name, key="__system__", shape=SHAPE_PACKAGE)

    for name, _ in entrypoints[:5]:
        node = diagram.node(name, key=f"in::{name}", shape="page")
        diagram.edge(node, centre)

    for name, data in datastores[:8]:
        shape = _STORE_SHAPES.get(str((data or {}).get("engine")), SHAPE_STORE)
        node = diagram.node(name, key=f"store::{name}", shape=shape)
        diagram.edge(centre, node, label="reads/writes")

    for name, _ in external[:8]:
        node = diagram.node(name, key=f"api::{name}", shape="cloud")
        diagram.edge(centre, node, label="calls")

    return diagram.render()


def blast_radius(path: str, dependents: list[dict]) -> str | None:
    """
    What a change to one file reaches.

    `dependents` is `[{file, distance}]` from the graph. Grouped by distance so the
    picture answers "how far does this go" rather than listing files — which the
    reader could get from a query.
    """
    if not dependents:
        return None

    diagram = D2Diagram(title=f"Impact of changing {path}", direction="right")
    centre = diagram.node(path, key="__target__", shape=SHAPE_PACKAGE)

    by_distance: dict[int, list[str]] = defaultdict(list)
    for row in dependents:
        by_distance[int(row.get("distance", 1))].append(str(row.get("file", "")))

    previous = centre
    for distance in sorted(by_distance)[:3]:
        files = sorted(f for f in by_distance[distance] if f)
        container = diagram.container(f"{distance} hop{'s' if distance > 1 else ''} away")
        for name in files[:8]:
            diagram.node(name, parent=container, key=f"d{distance}::{name}")
        if files:
            first = ident(f"d{distance}::{files[0]}")
            diagram.edge(previous, first, label=f"{len(files)} file(s)")
            previous = first

    return None if diagram.is_empty else diagram.render()


def entity_map(entities: list[dict], kind: str, title: str) -> str | None:
    """One kind of fact, drawn. Routes, scheduled tasks, infrastructure."""
    rows = _named(entities, kind)
    if len(rows) < 2:
        return None

    diagram = D2Diagram(title=title, direction="down")
    for name, data in rows[:16]:
        diagram.node(name, key=f"{kind}::{name}", tooltip=str((data or {}).get("path") or ""))
    return diagram.render()


def _named(entities: list[dict], kind) -> list[tuple[str, dict]]:
    return [
        (str(e.get("name") or ""), e.get("data_json") or {})
        for e in entities
        if str(e.get("kind")) == str(kind) and e.get("name")
    ]


__all__ = ["module_map", "system_context", "blast_radius", "entity_map"]
