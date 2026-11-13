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
agree it belongs nowhere, as far as analysis can say.

**Every file still gets a home** (`place_files`). What analysis said is never overruled;
for the rest, the evidence is in the code itself. A test goes with the tests, a file
for installing or running the code with those, and a source file the architecture pass
skipped joins the part its folder is in, or the part it is tied to by imports. Each
placement carries the reason, so a reader can see why a file is where it is, and a
file nothing ties to anything says so in *Other* rather than being dressed up.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

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


def assign(
    architecture: object, module_names: list[str], why: dict[str, str] | None = None
) -> dict[str, str]:
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
    it. What is left over stays unassigned here; `place_files` finds those files a home
    from the code, and says that it did.

    `why`, when given, is filled with one sentence per assigned module saying which
    pass placed it.
    """
    known = set(module_names)
    direct: dict[str, str] = {}
    for component in components(architecture):
        for module in component.modules:
            if module in known and module not in direct:
                direct[module] = component.name
                if why is not None:
                    why[module] = "Analysis listed it in this part."

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
            if why is not None:
                why[name] = f"{count} of the {total} modules inside it are in this part."

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
                if why is not None:
                    why[name] = f"It is inside `{ancestor}`, which is in this part."
                break

    return resolved


# -- A home for every file ----------------------------------------------------

TESTS = "Tests"
SETUP = "Build & run"
SCRIPTS = "Scripts & tooling"
OTHER = "Other"

#: The parts made here, by group: their name and what they hold. In this order after
#: the parts analysis named.
HOUSE_PARTS: dict[str, tuple[str, str]] = {
    "tests": (TESTS, "The test suite. Its links show which parts each test exercises."),
    "scripts": (SCRIPTS, "Scripts and entry points that stand apart from the rest of the code."),
    "setup": (
        SETUP,
        "What it takes to install, configure and run the code: dependency manifests, "
        "lockfiles, environment templates, containers and CI.",
    ),
    "other": (
        OTHER,
        "Files nothing in the code ties to a part: no folder-mates in one, and no imports "
        "either way.",
    ),
}

#: File kinds that are about running the code rather than being it.
SETUP_KINDS = frozenset({"manifest", "lockfile", "env", "deploy", "ci", "tooling", "docs"})

#: Folder names that hold scripts in every ecosystem.
_SCRIPT_DIRS = frozenset({"scripts", "script", "tools", "tooling", "bin", "hack", "devtools"})

#: A folder decides a file's part outright only when at least this share of its placed
#: files agree, and at least two of them do.
_FOLDER_SHARE = 0.6

#: Rounds of placing by folder and by imports. Each round can settle files the round
#: before made evidence for.
_ROUNDS = 6


@dataclass(frozen=True, slots=True)
class Placement:
    """Where one file sits and why."""

    part: str
    #: `component` for a part analysis named, otherwise a key of `HOUSE_PARTS`.
    group: str
    reason: str


def _times(n: int, what: str) -> str:
    return f"{n} {what}" if n == 1 else f"{n} {what}s"


def place_files(
    named: dict[str, str | None],
    kinds: dict[str, str],
    edges: Iterable[tuple[str, str]],
    why: dict[str, str] | None = None,
) -> dict[str, Placement]:
    """
    A part for every file in `named`, with the reason.

    `named` is what analysis said per file (`None` where it said nothing), `kinds` the
    atlas kind of each file, `edges` file imports as `(importer, imported)`, and `why`
    the sentence `assign` gave for a file analysis placed.

    Evidence, strongest first, and only ever from files placed in a named part -- a
    test importing a file says nothing about where the file belongs:

    1. what analysis said;
    2. a test goes to *Tests*, and a file about running the code to *Build & run*;
    3. a clear majority of the file's folder-mates;
    4. the part it is tied to by the most imports, either way;
    5. a plurality of its folder-mates, however slight;
    6. a script or entry point with no ties goes to *Scripts & tooling*; anything else
       to *Other*.

    3 and 4 run in rounds, each reading only what was settled before it, so the result
    does not depend on the order files are visited.
    """
    why = why or {}
    out: dict[str, Placement] = {}
    for path, part in named.items():
        if part:
            out[path] = Placement(part, "component", why.get(path) or "Analysis placed it in this part.")

    for path in named:
        if path in out:
            continue
        kind = kinds.get(path, "")
        if kind == "test":
            out[path] = Placement(TESTS, "tests", "It is a test.")
        elif kind in SETUP_KINDS:
            out[path] = Placement(SETUP, "setup", "It is about installing, configuring or running the code.")

    folder_of = {path: str(PurePosixPath(path).parent) for path in named}
    folders: dict[str, list[str]] = defaultdict(list)
    for path, folder in folder_of.items():
        folders[folder].append(path)

    imports: dict[str, Counter[str]] = defaultdict(Counter)
    imported_by: dict[str, Counter[str]] = defaultdict(Counter)
    for a, b in edges:
        if a != b and a in named and b in named:
            imports[a][b] += 1
            imported_by[b][a] += 1

    def folder_votes(path: str, settled: dict[str, Placement]) -> Counter[str]:
        votes: Counter[str] = Counter()
        for mate in folders[folder_of[path]]:
            placed = settled.get(mate)
            if mate != path and placed and placed.group == "component":
                votes[placed.part] += 1
        return votes

    def best(counts: Counter[str], tiebreak: Counter[str]) -> tuple[str, int]:
        return max(counts.items(), key=lambda kv: (kv[1], tiebreak.get(kv[0], 0), kv[0]))

    for _ in range(_ROUNDS):
        settled = dict(out)
        found: dict[str, Placement] = {}
        for path in sorted(p for p in named if p not in settled):
            votes = folder_votes(path, settled)
            if votes:
                part, n = best(votes, Counter())
                total = sum(votes.values())
                if n >= 2 and n / total >= _FOLDER_SHARE:
                    found[path] = Placement(
                        part, "component", f"{n} of the {_times(total, 'placed file')} beside it are in this part."
                    )
                    continue

            uses: Counter[str] = Counter()
            used: Counter[str] = Counter()
            for other, n in imports[path].items():
                placed = settled.get(other)
                if placed and placed.group == "component":
                    uses[placed.part] += n
            for other, n in imported_by[path].items():
                placed = settled.get(other)
                if placed and placed.group == "component":
                    used[placed.part] += n
            ties = uses + used
            if ties:
                part, _ = best(ties, votes)
                said = []
                if uses[part]:
                    said.append(f"it imports {_times(uses[part], 'file')} in this part")
                if used[part]:
                    said.append(f"{_times(used[part], 'file')} in this part import{'s' if used[part] == 1 else ''} it")
                text = " and ".join(said) + "."
                found[path] = Placement(part, "component", text[0].upper() + text[1:])
        if not found:
            break
        out.update(found)

    for path in sorted(p for p in named if p not in out):
        votes = folder_votes(path, out)
        if votes:
            part, n = best(votes, Counter())
            out[path] = Placement(
                part,
                "component",
                f"No imports either way; {_times(n, 'file')} beside it {'is' if n == 1 else 'are'} in this part.",
            )
        elif kinds.get(path) in ("cli", "entry") or any(
            seg.lower() in _SCRIPT_DIRS for seg in PurePosixPath(path).parts[:-1]
        ):
            out[path] = Placement(SCRIPTS, "scripts", "A script or entry point with no ties to a part.")
        else:
            out[path] = Placement(
                OTHER, "other", "Nothing ties it to a part: no folder-mates in one, and no imports either way."
            )
    return out


__all__ = [
    "HOUSE_PARTS",
    "OTHER",
    "SCRIPTS",
    "SETUP",
    "SETUP_KINDS",
    "TESTS",
    "Component",
    "Placement",
    "assign",
    "components",
    "place_files",
]
