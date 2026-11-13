"""
The shape of a codebase: its parts in the order a request meets them, and which parts
depend on which.

Two readers need the same answer. The knowledge graph draws the parts in columns —
where work comes in, core logic, shared helpers, data and outside services — and a
review checks a change against those columns: an import that runs backwards against
them, a dependency between two parts that had none, a new loop. If the two disagreed,
the map would say one thing and the review another, so the columns are decided here
once and the studio is handed them.

Decided from what analysis already stored, never from a language's file names: the
kinds of file a part is made of (`knowledge/atlas.py` `file_kind`), and which way the
imports between parts mostly run. A part that is mostly imported is leant on; one that
mostly imports does the leaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codelith.knowledge.atlas import Atlas

#: The columns, left to right. Indexes are what `component_tiers` returns.
TIERS: tuple[tuple[str, str], ...] = (
    ("Where work comes in", "Entry points, commands, routes, screens and the tests that drive them"),
    ("Core logic", "The parts that call more than they are called"),
    ("Shared helpers", "The parts the rest leans on"),
    ("Data and outside services", "Where it stores things and what it calls beyond the codebase"),
)

_ENTRY = frozenset({"entry", "cli", "api", "ui"})
_DATA = frozenset({"data", "store", "external"})


@dataclass(slots=True)
class Shape:
    """The parts, their columns, and the part-to-part links the reading found."""

    #: Per component index: its column, or -1 for a component with no nodes.
    tiers: list[int]
    #: (from component, to component) → how many file imports run that way.
    links: dict[tuple[int, int], int] = field(default_factory=dict)

    def reaches(self, start: int, goal: int, extra: set[tuple[int, int]] = frozenset()) -> bool:
        """Whether part `start` already depends on part `goal`, through any chain."""
        nxt: dict[int, set[int]] = {}
        for a, b in [*self.links, *extra]:
            nxt.setdefault(a, set()).add(b)
        seen = {start}
        todo = [start]
        while todo:
            x = todo.pop()
            if x == goal:
                return True
            for y in nxt.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    todo.append(y)
        return False


def part_links(atlas: Atlas) -> dict[tuple[int, int], int]:
    """File imports between different parts, counted per pair. Facts are left out:
    a file declaring a datastore is not the same thing as code depending on a part."""
    out: dict[tuple[int, int], int] = {}
    for a, b in atlas.edges:
        na, nb = atlas.nodes[a], atlas.nodes[b]
        if na.fact or nb.fact or na.component == nb.component:
            continue
        key = (na.component, nb.component)
        out[key] = out.get(key, 0) + 1
    return out


def component_tiers(atlas: Atlas) -> list[int]:
    """
    Each component's column. Mirrors the rules the graph used to apply on its own
    (`ui/src/app/components/atlas/model.ts`), which now reads these instead.
    """
    count = len(atlas.components)
    members = [0] * count
    kinds: list[dict[str, int]] = [{} for _ in range(count)]
    for node in atlas.nodes:
        members[node.component] += 1
        kinds[node.component][node.kind] = kinds[node.component].get(node.kind, 0) + 1

    # Links to facts count here (a part that only calls outside services still does
    # the leaning), though not in `part_links`, which is about code depending on code.
    into = [0] * count
    out = [0] * count
    for a, b in atlas.edges:
        ca, cb = atlas.nodes[a].component, atlas.nodes[b].component
        if ca != cb:
            out[ca] += 1
            into[cb] += 1

    tiers = [-1] * count
    for i, component in enumerate(atlas.components):
        n = members[i]
        if not n:
            continue

        def share(wanted: frozenset[str], i: int = i, n: int = n) -> float:
            return sum(v for k, v in kinds[i].items() if k in wanted) / n

        tests = kinds[i].get("test", 0) / n
        if component.group == "outside" or share(_DATA) >= 0.5:
            tiers[i] = 3
        elif component.group in ("config", "setup"):
            # Configuration, and what it takes to run the code: leant on, never leaning.
            # Ahead of the entry rule, since an env template links out to the fact it
            # declares and would otherwise read as something that receives work.
            tiers[i] = 2
        elif share(_ENTRY) >= 0.3 or tests >= 0.5 or (into[i] == 0 and out[i] > 0):
            tiers[i] = 0
        else:
            tiers[i] = 1 if (out[i] - into[i]) / (out[i] + into[i] + 1) >= 0 else 2
    return tiers


def shape_of(atlas: Atlas) -> Shape:
    return Shape(tiers=component_tiers(atlas), links=part_links(atlas))


__all__ = ["TIERS", "Shape", "component_tiers", "part_links", "shape_of"]
