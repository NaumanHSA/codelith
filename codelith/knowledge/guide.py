"""
The instruction file a coding agent reads first (AGENTS.md, CLAUDE.md), written from
the reading rather than from memory.

Agents work best with a short file at the top of a repository saying what it is, how it
is laid out, how to run it, and how things are done there. A hand-written one drifts;
this one is generated from what the reading found and can be regenerated after every
reading. No model is called: every sentence is assembled from facts with a file and a
line behind them, so it can be incomplete but not invented.

Two halves:

- **recipes** — "how is a route added here": where things of a kind are declared,
  where they are registered, and the clearest existing example. Also served alone by
  the `how_to` tool, because "follow the house style" is the instruction agents most
  often miss.
- **the file** — overview, the parts in their columns and the rule about which way
  imports run, how to run it, the recipes, the files where an edit is riskiest, and how
  to use Codelith while working. Wrapped in markers so a regenerated section replaces
  only itself and everything written by hand around it survives.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.atlas import Atlas, AtlasService
from codelith.knowledge.constants import EntityKind
from codelith.knowledge.risk import RiskService
from codelith.knowledge.services import HOUSE_PARTS
from codelith.knowledge.shape import TIERS, component_tiers
from codelith.models.knowledge import KBEntity, KBNarrative, KnowledgeBase
from codelith.models.project import Project

BEGIN = "<!-- codelith:begin -->"
END = "<!-- codelith:end -->"

#: (id, fact kind, title) for the recipes read from facts.
_FACT_RECIPES: tuple[tuple[str, str, str], ...] = (
    ("route", EntityKind.ROUTE, "Add an API route"),
    ("command", EntityKind.CLI_COMMAND, "Add a command"),
    ("scheduled_job", EntityKind.SCHEDULED_TASK, "Add a scheduled job"),
    ("event", EntityKind.EVENT, "Handle an event"),
    ("setting", EntityKind.ENV_VAR, "Add a setting"),
)
RECIPE_IDS = tuple(r[0] for r in _FACT_RECIPES) + ("model", "test")

_MANIFESTS = {"package.json", "pyproject.toml", "Makefile", "justfile", "setup.cfg", "Cargo.toml", "composer.json"}
_PLAIN_NAMES = {"__init__.py", "index.ts", "index.js", "index.tsx", "mod.rs", "doc.go"}


@dataclass(slots=True)
class Recipe:
    id: str
    title: str
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return f"{self.title}:\n" + "\n".join(f"- {line}" for line in self.lines)


def _folder(paths: list[str]) -> str:
    """The deepest folder all the paths share, as `folder/`; the most common one when
    they share nothing but the root."""
    parents = [PurePosixPath(p).parent.parts for p in paths]
    if not parents:
        return ""
    common: list[str] = []
    for level in zip(*parents, strict=False):
        if len(set(level)) != 1:
            break
        common.append(level[0])
    if common:
        return "/".join(common) + "/"
    top = Counter("/".join(p[:2]) for p in parents if p).most_common(1)
    return (top[0][0] + "/") if top else ""


def _code(text: str) -> str:
    return f"`{text}`"


class GuideService:
    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb
        self._atlas: Atlas | None = None

    async def atlas(self) -> Atlas:
        if self._atlas is None:
            self._atlas = await AtlasService(self.db, self.kb).build()
        return self._atlas

    # ── recipes ──────────────────────────────────────────────────────────────

    async def recipes(self) -> list[Recipe]:
        atlas = await self.atlas()
        importers: dict[str, list[str]] = {}
        kinds: dict[str, str] = {}
        for node in atlas.nodes:
            if not node.fact:
                kinds[node.path] = node.kind
        for a, b in atlas.edges:
            na, nb = atlas.nodes[a], atlas.nodes[b]
            if not na.fact and not nb.fact:
                importers.setdefault(nb.path, []).append(na.path)

        rows = (
            await self.db.execute(
                select(KBEntity.kind, KBEntity.name, KBEntity.source_path, KBEntity.source_line).where(
                    KBEntity.kb_id == self.kb.id,
                    KBEntity.kind.in_([str(k) for _, k, _ in _FACT_RECIPES]),
                )
            )
        ).all()
        by_kind: dict[str, list[tuple[str, str | None, int | None]]] = {}
        for kind, name, path, line in rows:
            by_kind.setdefault(str(kind), []).append((name, path, line))

        out: list[Recipe] = []
        for rid, kind, title in _FACT_RECIPES:
            facts = [
                f
                for f in by_kind.get(str(kind), [])
                if f[1]
                and kinds.get(f[1]) != "test"
                # A script in a manifest is run, not written like the code's own commands.
                and not (rid == "command" and PurePosixPath(f[1]).name in _MANIFESTS)
            ]
            if not facts:
                continue
            files = Counter(path for _, path, _ in facts)
            top = [p for p, _ in files.most_common(3)]
            recipe = Recipe(rid, title)
            noun = {"route": "routes", "command": "commands", "scheduled_job": "scheduled jobs", "event": "event handlers", "setting": "settings"}[rid]
            where = _folder(list(files))
            if rid == "setting":
                recipe.lines.append(
                    f"{len(facts)} {noun} are read, most in {_code(top[0])}"
                    + (f" ({files[top[0]]} of them)" if files[top[0]] > 1 else "")
                    + ". Add a new one there, next to the others, rather than reading the environment elsewhere."
                )
                recipe.lines.append("For example: " + ", ".join(_code(n) for n, _, _ in facts[:4]) + ".")
            else:
                recipe.lines.append(
                    f"{len(facts)} {noun} are declared"
                    + (f" under {_code(where)}" if where else "")
                    + f", most in {_code(top[0])}"
                    + (f" and {_code(top[1])}" if len(top) > 1 else "")
                    + "."
                )
                example = next(((n, p, ln) for n, p, ln in facts if p == top[0] and ln), facts[0])
                where_line = f"{example[1]}:{example[2]}" if example[2] else str(example[1])
                recipe.lines.append(f"Follow an existing one: {_code(example[0])} in {_code(where_line)}.")
                # Where new ones are wired in: the file that imports most of the declaring ones.
                wiring = Counter(
                    imp for path in files for imp in importers.get(path, []) if kinds.get(imp) != "test" and imp not in files
                )
                if wiring:
                    hub, count = wiring.most_common(1)[0]
                    if count >= 2:
                        recipe.lines.append(
                            f"Files that declare them are registered in {_code(hub)}, which imports {count} of them; "
                            "a new file needs adding there too."
                        )
            out.append(recipe)

        models = [p for p, k in kinds.items() if k == "model"]
        if models:
            recipe = Recipe("model", "Add a model or schema")
            folders = Counter(str(PurePosixPath(p).parent) for p in models).most_common(2)
            recipe.lines.append(
                f"{len(models)} files hold models and schemas, mostly in "
                + " and ".join(_code(f + "/") for f, _ in folders)
                + "."
            )
            telling = sorted(p for p in models if PurePosixPath(p).name not in _PLAIN_NAMES) or sorted(models)
            recipe.lines.append(f"Follow an existing one, such as {_code(telling[0])}.")
            out.append(recipe)

        tests = [p for p, k in kinds.items() if k == "test"]
        if tests:
            recipe = Recipe("test", "Add a test")
            folders = Counter(
                "/".join(PurePosixPath(p).parent.parts[:2]) for p in tests if PurePosixPath(p).parent.parts
            ).most_common(3)
            names = [PurePosixPath(p).name for p in tests]
            pattern = None
            if sum(n.startswith("test_") for n in names) * 2 > len(names):
                pattern = "test_*" + (PurePosixPath(names[0]).suffix or "")
            elif sum(".test." in n for n in names) * 2 > len(names):
                pattern = "*.test.*"
            elif sum(".spec." in n for n in names) * 2 > len(names):
                pattern = "*.spec.*"
            elif sum(n.endswith("_test.go") for n in names) * 2 > len(names):
                pattern = "*_test.go"
            recipe.lines.append(
                f"{len(tests)} test files, in "
                + ", ".join(_code(f + "/") for f, _ in folders)
                + (f", named {_code(pattern)}" if pattern else "")
                + "."
            )
            out.append(recipe)
        return out

    async def recipe(self, rid: str) -> Recipe | None:
        return next((r for r in await self.recipes() if r.id == rid), None)

    # ── the file ─────────────────────────────────────────────────────────────

    async def markdown(self, fmt: str = "agents") -> str:
        kb = self.kb
        atlas = await self.atlas()
        project = await self.db.get(Project, kb.project_id)
        name = project.name if project else "This codebase"
        tiers = component_tiers(atlas)

        out: list[str] = [
            BEGIN,
            f"<!-- Written by Codelith from the reading of {name} at {(kb.commit_sha or 'unknown')[:8]}. "
            "`codelith agents-md --write` rewrites this section after a new reading and leaves the rest of "
            "the file alone. -->",
            "",
            "## About this codebase",
            "",
        ]
        overview = await self._overview()
        out += [overview or f"{name}, as Codelith read it.", ""]

        # The parts in their columns, and the rule that follows from them.
        members: Counter[int] = Counter(n.component for n in atlas.nodes if not n.fact)
        folders: dict[int, Counter[str]] = {}
        for n in atlas.nodes:
            parent = PurePosixPath(n.path).parent.parts[:2]
            if not n.fact and parent:
                folders.setdefault(n.component, Counter())["/".join(parent)] += 1
        out += ["## How the code is laid out", ""]
        for t, (title, _hint) in enumerate(TIERS):
            parts = [
                c
                for c in range(len(atlas.components))
                if tiers[c] == t and members[c] and atlas.components[c].group not in HOUSE_PARTS
            ]
            if not parts:
                continue
            out.append(f"**{title}**")
            out.append("")
            for c in sorted(parts, key=lambda c: -members[c]):
                comp = atlas.components[c]
                where = ", ".join(_code(f + "/") for f, _ in folders.get(c, Counter()).most_common(2))
                desc = (comp.description or "").strip().rstrip(".")
                out.append(f"- **{comp.name}** ({members[c]} files{', ' + where if where else ''})" + (f" — {desc}." if desc else ""))
            out.append("")
        out += [
            "Imports run down that list: what takes work in calls the core, the core leans on the "
            "shared helpers, and data and outside services are reached last. A change that makes a part "
            "import one listed above it, or makes two parts depend on each other, changes how the code "
            "is put together — check it with `codelith review` or the `review_changes` tool.",
            "",
        ]

        from codelith.knowledge.runbook import RunbookService

        book = await RunbookService(self.db, self.kb).build()
        if book.available and not book.empty:
            out += [book.markdown("## Running it"), ""]
        elif running := await self._running():
            out += ["## Running it", "", *running, ""]

        recipes = await self.recipes()
        if recipes:
            out += ["## How things are done here", ""]
            for r in recipes:
                out.append(f"**{r.title}.** " + " ".join(r.lines))
                out.append("")

        risky, _ = await RiskService(self.db, kb).rank(limit=40)
        risky = [r for r in risky if r.tests == 0 and r.reach >= 3][:8]
        if risky:
            out += [
                "## Edit these with care",
                "",
                "No test reaches these, and many files depend on them:",
                "",
                *(f"- {_code(r.path)} — {r.reach} files reach it ({r.component})" for r in risky),
                "",
            ]

        from codelith.knowledge.findings import FindingsReader

        serious = await FindingsReader(self.db, kb.project_id).open(min_severity="high", limit=10)
        if serious:
            out += [
                "## Known problems",
                "",
                "Open QA findings, critical and high, that nobody has dismissed. Do not copy these "
                "patterns; fix one if you are working in its file:",
                "",
                *(f"- **{k.severity}** {k.title} — {_code(k.where)}" for k in serious),
                "",
            ]

        out += [
            "## Working with Codelith",
            "",
            "If the Codelith MCP server is connected (`codelith mcp`):",
            "",
            "- before editing a file or function, call `before_edit` — what depends on it, its tests, the pages that describe it;",
            "- to understand a route or command, call `trace_flow` — the path from its handler to the data;",
            "- to follow the house style, call `how_to` with route, command, setting, model or test;",
            "- to install, run or test it, call `how_to` with run;",
            "- for known security holes, bugs and test gaps, call `qa_findings` (with a path to narrow it);",
            "- after editing, call `review_changes` and fix anything under *Stop and look* before finishing.",
            "",
            END,
        ]
        text = "\n".join(out).rstrip() + "\n"
        return text

    async def _overview(self) -> str | None:
        row = (
            await self.db.execute(
                select(KBNarrative.content_md).where(KBNarrative.kb_id == self.kb.id, KBNarrative.topic == "overview")
            )
        ).scalar_one_or_none()
        if not row:
            return None
        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", row)
            if p.strip() and not p.lstrip().startswith(("#", "|", "```", "- ", "* "))
        ]
        text = "\n\n".join(paragraphs[:2])
        if len(text) > 1400:
            cut = text[:1400]
            stop = cut.rfind(". ")
            text = cut[: stop + 1] if stop > 400 else cut.rstrip() + "…"
        return text

    async def _running(self) -> list[str]:
        rows = (
            await self.db.execute(
                select(KBEntity.kind, KBEntity.name, KBEntity.source_path).where(
                    KBEntity.kb_id == self.kb.id,
                    KBEntity.kind.in_([str(EntityKind.ENTRYPOINT), str(EntityKind.CLI_COMMAND), str(EntityKind.TEST_SUITE)]),
                )
            )
        ).all()
        entry = [n for k, n, _ in rows if k == EntityKind.ENTRYPOINT][:5]
        scripts = [n for k, n, _ in rows if k == EntityKind.CLI_COMMAND and re.match(r"^(npm|pnpm|yarn|make|just|poetry|uv) ", n)][:8]
        suites = [n for k, n, _ in rows if k == EntityKind.TEST_SUITE][:4]
        lines: list[str] = []
        if entry:
            lines.append("- Entry points: " + ", ".join(_code(e) for e in entry))
        if scripts:
            lines.append("- Scripts: " + ", ".join(_code(s) for s in scripts))
        if suites:
            lines.append("- Tests: " + ", ".join(_code(s) for s in suites))
        return lines


def merge(existing: str | None, section: str, title: str) -> str:
    """The file with the generated section put in place: replaced between its markers when
    it is there, appended when it is not, or the whole file when there is none."""
    if not existing:
        return f"# {title}\n\n{section}"
    start, end = existing.find(BEGIN), existing.find(END)
    if start != -1 and end != -1 and end > start:
        return existing[:start] + section.rstrip("\n") + existing[end + len(END):]
    return existing.rstrip() + "\n\n" + section


__all__ = ["BEGIN", "END", "RECIPE_IDS", "GuideService", "Recipe", "merge"]
