"""
Checking generated prose against the code it claims to describe.

For AI-written documentation, *"here is what we could not ground"* is what makes the
rest trustable. Without it every sentence carries the same weight, and the reader has
no way to tell the paragraph derived from a function signature from the one the model
filled in because the section looked thin.

**Measured deterministically, not by asking a model.** A second model grading the
first is expensive, non-reproducible, and wrong in correlated ways — it tends to
approve exactly the confident-sounding invention a reader would also miss. Instead
this checks the one thing a knowledge base can settle absolutely: *does this
paragraph name things that exist?*

    "The `SessionFactory` in `app/db/session.py` builds the engine."
      → SessionFactory ✓ known symbol
      → app/db/session.py ✓ known file            → grounded

    "The `WorkerPool` dispatches to `app/queue/manager.py`."
      → WorkerPool ✗ no such symbol
      → app/queue/manager.py ✗ no such file        → unverified

That is not a proof of truth — a paragraph can name real things and still describe
them wrongly. It is a proof of *reference*, which catches the failure mode that
actually occurs: run 2 of the diagram agent invented `Workers`, `Storage` and a
`Feedback Loop` for a codebase containing none of them, and nothing downstream
noticed.

Only code-shaped tokens count. An ordinary English word is not a claim about the
repository, and treating one as an identifier was measurably wrong in the question
router — "what calls the tool registry" matched a symbol named `tool`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Tokens that assert something about the code: backticked, a path, dotted,
#: snake_case, or CamelCase. Prose does not have these shapes by accident.
_CLAIM = re.compile(
    r"`([^`\n]+)`"                                          # `anything backticked`
    r"|\b([\w./-]+/[\w.-]+\.\w{1,5})\b"                     # a/b/c.py
    r"|\b([A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+)\b"          # CamelCase
    r"|\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b"                 # snake_case
)

#: Fenced code and headings are excluded: a code block is the evidence, not a claim
#: about it, and a heading is a label.
_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_HEADING = re.compile(r"^#{1,6}\s+.*$", re.M)

#: `self.thing` and `this.thing` are attribute accesses inside a method, not claims
#: about the repository's structure. The KB indexes declarations, not every attribute,
#: so checking them reports a problem for every correct sentence that mentions one.
_ATTRIBUTE_ACCESS = re.compile(r"^(self|this|cls)\.")

#: Words that match a shape above but assert nothing about this repository.
_NOT_A_CLAIM = frozenset({
    "JSON", "YAML", "HTTP", "HTTPS", "REST", "API", "URL", "URI", "SQL", "HTML",
    "CSS", "JavaScript", "TypeScript", "Python", "PostgreSQL", "GitHub", "OpenAI",
    "README", "TODO", "NOTE", "ID", "UUID", "JWT", "CLI", "UI", "CI", "CD",
    "GET", "POST", "PUT", "PATCH", "DELETE", "OK",
})

#: A paragraph shorter than this is a fragment — a list item, a caption — and holding
#: it to the same standard produces noise rather than signal.
_MIN_WORDS = 8


@dataclass(slots=True)
class Claim:
    """One identifier a paragraph asserted, and whether the codebase has it."""

    text: str
    known: bool


@dataclass(slots=True)
class Paragraph:
    index: int
    excerpt: str
    claims: list[Claim] = field(default_factory=list)

    @property
    def unknown(self) -> list[str]:
        return [c.text for c in self.claims if not c.known]

    @property
    def grounded(self) -> bool:
        """Names something real, and nothing unreal."""
        return any(c.known for c in self.claims) and not self.unknown

    @property
    def unverified(self) -> bool:
        """Names something the codebase does not contain."""
        return bool(self.unknown)


@dataclass(slots=True)
class GroundingReport:
    """What a page claims, and how much of it holds up."""

    paragraphs: int = 0
    grounded: int = 0
    unverified: int = 0
    #: Paragraphs that assert nothing checkable. Neither good nor bad — an
    #: introduction naming no identifier is doing its job.
    unchecked: int = 0
    #: The specific problems, for a reader to open. Capped: a page with forty is
    #: broken in a way a list does not help with.
    problems: list[dict] = field(default_factory=list)

    @property
    def score(self) -> float:
        """
        Grounded share of the paragraphs that made a checkable claim.

        Deliberately excludes `unchecked` from the denominator. Including it would
        punish a well-written introduction and reward a page that names nothing.
        """
        checkable = self.grounded + self.unverified
        return round(self.grounded / checkable, 3) if checkable else 1.0

    def to_dict(self) -> dict:
        return {
            "paragraphs": self.paragraphs,
            "grounded": self.grounded,
            "unverified": self.unverified,
            "unchecked": self.unchecked,
            "score": self.score,
            "problems": self.problems,
        }


def check_page(markdown: str, known: frozenset[str], *, max_problems: int = 12) -> GroundingReport:
    """
    Every paragraph of a page, checked against what the knowledge base contains.

    `known` must be *everything nameable* — the repository's own symbols, files and
    modules, **and the names it imports from elsewhere**. Built from declarations
    alone this under-reports badly: measured on the neurosurfer site it flagged
    `FastAPI`, `ThreadPoolExecutor` and `tool_use` as unknown, none of which is an
    invention, and scored sound pages at 0.27. `vocabulary_for` assembles the right
    set; a caller passing something narrower will get numbers that punish correct
    prose for mentioning a library.

    Matching tries a few spellings of each token, so `session.py`,
    `app/db/session.py` and `SessionFactory.build` all resolve without the caller
    pre-computing every form.
    """
    report = GroundingReport()

    for index, text in enumerate(_paragraphs(markdown), start=1):
        if len(text.split()) < _MIN_WORDS:
            continue

        report.paragraphs += 1
        claims = [
            Claim(text=token, known=_is_known(token, known))
            for token in _claims_in(text)
        ]
        paragraph = Paragraph(index=index, excerpt=text[:220], claims=claims)

        if not claims:
            report.unchecked += 1
        elif paragraph.unverified:
            report.unverified += 1
            if len(report.problems) < max_problems:
                report.problems.append({
                    "paragraph": index,
                    "excerpt": paragraph.excerpt,
                    "unknown": paragraph.unknown[:6],
                })
        else:
            report.grounded += 1

    return report


async def vocabulary_for(db, kb_id: int, project_id: int) -> frozenset[str]:
    """
    Everything this knowledge base can name, in every spelling worth matching.

    The set has to include what the repository *imports*, not only what it declares.
    Built from declarations alone, the first run of this flagged `FastAPI`,
    `ThreadPoolExecutor` and `tool_use` as ungrounded and scored sound pages at 0.27
    — a number that punishes correct prose for mentioning a library, which would
    have made the whole surface worse than useless.
    """
    from codelith.db.repositories.knowledge import KnowledgeRepositories
    from codelith.knowledge.constants import EntityKind

    repos = KnowledgeRepositories.for_session(db)
    known: set[str] = set()

    for module in await repos.modules.list_by_kb(kb_id):
        known.add(module.path)
        known.add(module.name)
        for path in module.files_json or []:
            known.add(path)
            known.add(path.rsplit("/", 1)[-1])
        for symbol in module.symbols_json or []:
            if name := symbol.get("name"):
                known.add(name)

    # Entity names cover routes, datastores, env vars and — importantly — the
    # dependency list, which is where `fastapi`, `pydantic` and `react` come from.
    for kind in EntityKind:
        for entity in await repos.entities.list_by_kind(kb_id, kind, limit=400):
            if entity.name:
                known.add(entity.name)
                # `org.springframework.boot:spring-boot-starter-web` and
                # `@tanstack/react-query` are also referred to by their last segment.
                known.add(re.split(r"[:/]", entity.name)[-1])

    # Names imported from anywhere, which is what makes third-party classes
    # groundable. Read from the graph's package edges plus every import target.
    known |= await _imported_names(project_id, kb_id)
    return frozenset(n for n in known if n)


async def _imported_names(project_id: int, kb_id: int) -> set[str]:
    """External packages this repository depends on, from the code graph."""
    from codelith.memory import get_graph_store

    try:
        async with get_graph_store() as graph:
            rows = await graph.get_packages(project_id, kb_id)
    except Exception:  # pragma: no cover - Neo4j optional
        return set()

    out: set[str] = set()
    for row in rows:
        if name := row.get("name"):
            out.add(name)
            out.add(re.split(r"[./]", name)[-1])
    return out


def _paragraphs(markdown: str) -> list[str]:
    body = _FENCE.sub(" ", markdown or "")
    body = _INLINE_HEADING.sub(" ", body)
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def _claims_in(text: str) -> list[str]:
    out: list[str] = []
    for groups in _CLAIM.findall(text):
        for token in groups:
            token = (token or "").strip()
            if not token or token in _NOT_A_CLAIM:
                continue
            # A backticked phrase with spaces is prose in code font, not an identifier.
            if " " in token or _ATTRIBUTE_ACCESS.match(token):
                continue
            if token not in out:
                out.append(token)
    return out


def _is_known(token: str, known: frozenset[str]) -> bool:
    """
    Whether the codebase contains this, tried in a few reasonable spellings.

    A writer legitimately says `session.py` for `app/db/session.py`, and
    `RevisionService.rekey_anchor` for a method recorded as `rekey_anchor`. Refusing
    those would report false problems, which is worse than missing a real one — a
    groundedness surface nobody trusts is a groundedness surface nobody reads.
    """
    if token in known:
        return True

    stripped = token.strip("()[]{}.,;:")
    if stripped in known:
        return True
    # A call written with parentheses.
    if stripped.endswith("()") and stripped[:-2] in known:
        return True
    # `Class.method` → either half.
    if "." in stripped:
        head, _, tail = stripped.rpartition(".")
        if tail in known or head in known:
            return True
    # A path written as its basename, or as a suffix of a real path.
    if "/" in stripped:
        tail = stripped.rsplit("/", 1)[-1]
        if tail in known:
            return True
        return any(path.endswith(f"/{stripped}") for path in known if "/" in path)
    return False


__all__ = ["check_page", "vocabulary_for", "GroundingReport", "Paragraph", "Claim"]
