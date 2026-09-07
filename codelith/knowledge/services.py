"""
Grouping modules the way this codebase is actually built, not the way every codebase is.

`ModuleRole` is a closed vocabulary — `api`, `service`, `data_access`, `test` and nine
others — assigned by matching directory names against a hint table. It is stable, which
is what makes it useful to the apps that consume it: an API reference asks for the `api`
modules, and it has to mean the same thing in every repository.

It is also the same twelve words in every repository, which is exactly the complaint.
`SERVICE` tells you a module is not a test; it does not tell you this is the *face
tracking engine*.

Analysis already knows better. The architecture pass reads the whole codebase once and
writes `architecture_json.services`: components named for what this system does, each
with the modules that make it up. Watchtower comes back with "Worker Face Tracking
Engine" and "Controller Persistence"; Neurosurfer with "RAG and Retrieval" and "Graph
Workflow Engine". Those are derived per codebase, from the code, by the analysis that
has already run.

So nothing new is computed here and no model is called. This reads what analysis wrote
and answers one question: which component does this module belong to. Roles stay exactly
where they were, because the apps still need a stable word.

**Coverage is partial and that is expected.** The architecture pass names leaf modules
and skips the parent packages that merely contain them, so a direct reading covers
between half and all of a repository. The gap is closed by descent rather than by
guessing: `codelith.agents` belongs wherever its children agree, and where they do not
agree it belongs nowhere, which is the honest answer.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Below this, a parent is not treated as belonging to the component its children are
#: in. Two thirds, so a package whose modules mostly serve one component inherits it
#: and one that is genuinely mixed does not.
_INHERIT_SHARE = 0.66


@dataclass(frozen=True, slots=True)
class Component:
    """One component analysis identified, and what it is made of."""

    name: str
    kind: str
    description: str
    modules: tuple[str, ...]


def components(architecture: object) -> list[Component]:
    """
    The components analysis named, cleaned up enough to rely on.

    `architecture_json` is a JSON column holding whatever was written to it, including
    a scalar, so every level is checked rather than assumed.
    """
    if not isinstance(architecture, dict):
        return []
    raw = architecture.get("services")
    if not isinstance(raw, list):
        return []

    out: list[Component] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        mods = item.get("modules")
        out.append(
            Component(
                name=name,
                kind=str(item.get("type") or "").strip(),
                description=str(item.get("description") or "").strip(),
                modules=tuple(
                    str(m).strip() for m in mods if isinstance(m, str) and str(m).strip()
                )
                if isinstance(mods, list)
                else (),
            )
        )
    return out


def assign(architecture: object, module_names: list[str]) -> dict[str, str]:
    """
    Which component each module belongs to. Modules with no answer are left out.

    Three passes, and only the first is what analysis literally said.

    1. **Direct**, from the component's own module list.
    2. **Descent**, for the parent packages the architecture pass skipped: it names
       leaves and rarely the package containing them. A package inherits only when a
       clear majority of its descendants agree, so `codelith.apps` — holding
       documentation, ask and drift — correctly belongs to none of them.
    3. **Ascent**, for the leaves it skipped the other way. A submodule of the agent
       runtime is part of the agent runtime; the nearest assigned ancestor wins, so a
       deep module takes the most specific answer available rather than the broadest.

    Together these take a real repository from roughly half assigned to nearly all of
    it. What is left over stays unassigned, which is the honest answer for a module
    the architecture pass never placed and whose neighbours disagree.
    """
    known = set(module_names)
    direct: dict[str, str] = {}
    for component in components(architecture):
        for module in component.modules:
            if module in known and module not in direct:
                direct[module] = component.name

    resolved = dict(direct)

    # 2. Descent: a package takes the component its children mostly serve. Voted from
    #    `direct` only, so an inherited answer never becomes evidence for another.
    for name in module_names:
        if name in resolved:
            continue
        prefix = f"{name}."
        votes: dict[str, int] = {}
        total = 0
        for child, component in direct.items():
            if child.startswith(prefix):
                votes[component] = votes.get(component, 0) + 1
                total += 1
        if not total:
            continue
        winner, count = max(votes.items(), key=lambda kv: (kv[1], kv[0]))
        if count / total >= _INHERIT_SHARE:
            resolved[name] = winner

    # 3. Ascent: a leaf takes its nearest assigned ancestor. Longest prefix first, so
    #    `neurosurfer.agents.conversation` prefers `neurosurfer.agents` over
    #    `neurosurfer`.
    #
    #    **Never from the root package**, which is the whole repository and therefore
    #    says nothing. Allowing it, `codelith` was placed in "Codelith API" and every
    #    module without an answer of its own inherited that — including `codelith.mcp`,
    #    which is a second transport over the knowledge base and not the API at all.
    #    Coverage went up and the labels stopped being true, which is the wrong trade.
    settled = dict(resolved)
    for name in module_names:
        if name in resolved:
            continue
        parts = name.split(".")
        for cut in range(len(parts) - 1, 1, -1):
            ancestor = ".".join(parts[:cut])
            if (component := settled.get(ancestor)) is not None:
                resolved[name] = component
                break

    return resolved


__all__ = ["Component", "assign", "components"]
