"""
Deciding whether a question is about this codebase at all.

`QuestionRouter` chooses *which store* answers a question. It has no way to conclude
that none of them should: everything handed to it is routed, so "what is the capital
of France" comes back with the three code chunks whose embeddings sit closest to it —
a real answer to a question nobody asked. The reader then gets a paragraph about
their own repository, cited from the files that were least unlike a country.

So there is a gate in front of retrieval, and it is built from three things.

* **What this repository is about, in the words analysis chose for it.** Not a
  general "is this a programming question" classifier: the components the
  architecture pass named, the overview it wrote, the stack it found, the questions
  it thought worth asking. A repository about elections *does* answer questions about
  countries, and a gate that does not know what the code is about cannot tell that
  repository from a compiler.
* **The conversation.** "and France?" is not a question about anything on its own.
  Read after two turns about the country table it plainly is, and a gate that judges
  each question in isolation refuses the second half of every dialogue.
* **A shortcut, so most questions never reach a model.** A question naming a
  component, a module, the stack, the project itself, or anything path- or
  backtick-shaped is about the code by construction — there is nothing to weigh. What
  reaches the call is the genuinely ambiguous remainder, which is also exactly the
  set worth spending a quality-tier call on.

**It fails open, always.** An unreachable model, an unparseable reply, a verdict that
is not one of the three — each answers `code`. Searching a repository for a question
it cannot answer wastes a few seconds; refusing a real question about somebody's own
code is the failure this must never make, and from the reader's side it is
indistinguishable from the product being broken.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.core.cancellation import JobCancelled
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.constants import NarrativeTopic
from codelith.knowledge.services import components

logger = structlog.get_logger(__name__)

#: Search the knowledge base and answer from it — the normal path.
CODE = "code"
#: About this conversation, or about the assistant. Answered, but not from the code:
#: a greeting routed into vector search returns the three chunks least unlike "hi".
CHAT = "chat"
#: General knowledge, or somebody else's codebase. Declined, and the code is not read.
OFF_TOPIC = "off_topic"

_VERDICTS = frozenset({CODE, CHAT, OFF_TOPIC})

#: Words that are in every repository's vocabulary and therefore identify none of
#: them. Without this, "how does the service handle a request" matches a component
#: called anything at all, and the shortcut below fires on every question ever asked.
#: Language names are here for the same reason and one more: "how do I reverse a list
#: in python" is not a question about *this* Python project, and the model is better
#: placed to decide that than a word match is.
_GENERIC = frozenset({
    "python", "typescript", "javascript", "java", "golang", "rust", "ruby", "php",
    "kotlin", "swift", "scala", "node", "nodejs", "html", "css",
    "service", "services", "server", "client", "system", "application", "module",
    "modules", "package", "packages", "library", "framework", "backend", "frontend",
    "code", "codebase", "file", "files", "data", "database", "project", "repository",
    "repo", "main", "core", "common", "util", "utils", "helper", "helpers", "shared",
    "test", "tests", "docs", "doc", "source", "apps", "component", "components",
    "interface", "manager", "handler", "engine", "layer", "layers", "controller",
    "model", "models", "view", "views", "config", "settings", "logic", "type",
    "types", "base", "generic", "custom", "internal", "external", "public",
})

#: A word worth remembering as this repository's own. Three letters and up, because
#: "id", "ui" and "db" match half of English.
_WORD = re.compile(r"[a-z][a-z0-9]{2,}")

#: Shapes that only a question about code has: a repo-relative path, a filename with
#: a real extension, or something the asker put in backticks.
#:
#: Deliberately *not* CamelCase or snake_case, which the router uses for a different
#: job. `OpenAI` and `New_York` are both, and neither is about anybody's repository —
#: as a shortcut past the gate they would wave through the questions the gate exists
#: to catch. Ambiguous shapes are the model's to judge.
_CODE_SHAPED = re.compile(
    r"`[^`\n]+`"
    r"|\b[\w.-]+/[\w.-]+\.\w{1,5}\b"
    r"|\b[\w-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|go|java|rb|rs|php|kt|cs|cpp|swift|scala"
    r"|md|rst|json|ya?ml|toml|ini|cfg|sh|bash|sql|tf|lock)\b",
    re.I,
)

#: How much of each part of the profile the model is shown. It is a description of a
#: repository, not the repository — past this it stops helping and starts competing
#: with the question for attention.
_SUMMARY_CHARS = 700
_MAX_COMPONENTS = 10
_MAX_MODULES = 20
_MAX_EXAMPLES = 5
_DESCRIPTION_CHARS = 120

#: Turns of history the gate reads, and how much of each. Shorter than the answering
#: prompt's window on purpose: what a follow-up refers to is in the last exchange or
#: two, and the rest is a second subject the gate can only be confused by.
#:
#: Not shorter still, because the gate also writes the reply for anything it declines,
#: and "what were we just talking about" is answered from exactly this text.
_HISTORY_TURNS = 6
_HISTORY_CHARS = 400


@dataclass(frozen=True, slots=True)
class CodebaseProfile:
    """
    What this repository is about, assembled from what analysis already wrote.

    Nothing here is derived and no model is called: the architecture pass named the
    components and found the stack, the narrative pass wrote the overview, and the
    question seeder wrote the examples. This reads them.

    `terms` is the part the gate can act on without a model — the words that belong
    to *this* codebase and not to codebases in general.
    """

    project_name: str
    summary: str = ""
    #: `name — what it is for`, as analysis described each component.
    component_lines: tuple[str, ...] = ()
    stack: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    #: Questions analysis thought worth asking about this repository. They double as
    #: the examples offered back to somebody whose question was declined.
    examples: tuple[str, ...] = ()
    terms: frozenset[str] = frozenset()

    @classmethod
    def build(
        cls,
        project_name: str,
        architecture: object = None,
        overview: str = "",
        suggestions: object = None,
    ) -> CodebaseProfile:
        """
        Assemble from the raw KB columns.

        Every level is checked rather than assumed: `architecture_json` is model
        output in a JSON column and may hold a scalar, a missing key, or a list of
        strings where a list of objects was expected.
        """
        found = components(architecture)
        stack = _stack(architecture)
        modules = _modules(architecture, found)
        examples = tuple(
            str(q).strip()
            for q in (suggestions if isinstance(suggestions, list) else [])
            if str(q).strip()
        )[:_MAX_EXAMPLES]

        component_lines = tuple(
            f"{c.name} — {c.description[:_DESCRIPTION_CHARS]}" if c.description else c.name
            for c in found[:_MAX_COMPONENTS]
        )

        return cls(
            project_name=project_name,
            summary=_first_prose(overview)[:_SUMMARY_CHARS],
            component_lines=component_lines,
            stack=stack,
            modules=modules,
            examples=examples,
            terms=_terms(project_name, found, stack, modules),
        )

    @property
    def is_thin(self) -> bool:
        """
        True when analysis left too little to judge relevance against.

        A degraded reading, or a repository so small the architecture pass found
        nothing to name. The gate is told, so it can lean towards answering rather
        than declining on the strength of a description it does not have.
        """
        return not self.summary and not self.component_lines

    def mentions(self, question: str) -> tuple[str, ...]:
        """
        Words in the question that belong to this repository.

        The whole shortcut, and the reason the gate is not a general-purpose topic
        classifier: a question naming a component, a module, the stack or the project
        is about the code, and no model needs to be asked.
        """
        if not self.terms:
            return ()
        words = set(_WORD.findall(question.lower()))
        return tuple(sorted(words & self.terms))[:5]

    def render(self) -> str:
        """The profile as the model sees it."""
        lines = [f"Repository: {self.project_name}"]
        if self.summary:
            lines.append(f"What it is: {self.summary}")
        if self.component_lines:
            lines.append("Components analysis named:")
            lines.extend(f"  - {line}" for line in self.component_lines)
        if self.stack:
            lines.append(f"Stack: {', '.join(self.stack)}")
        if self.modules:
            lines.append(f"Modules: {', '.join(self.modules)}")
        if self.examples:
            lines.append("Questions this repository is known to answer:")
            lines.extend(f"  - {q}" for q in self.examples)
        if self.is_thin:
            # Said plainly rather than left as an absence. A model shown three module
            # names and no description will decline anything it does not recognise,
            # and what it does not recognise is most of a repository it was told
            # nothing about.
            lines.append(
                "(Analysis recorded little about this repository beyond the names "
                "above, so absence of a subject here is not evidence of anything.)"
            )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ScopeVerdict:
    """What the gate decided, and what decided it."""

    verdict: str = CODE
    reason: str = ""
    #: Shown to the asker when the verdict is not `code`. Never an answer to the
    #: question — the point is that this one is not being answered from the code.
    reply: str = ""
    #: `vocabulary` · `shape` · `llm` · `fallback` · `disabled`. Recorded because a
    #: decision reached without a model and one reached by a model that then failed
    #: are not equally trustworthy, and the studio should not blur them.
    decided_by: str = "vocabulary"
    #: The repository's own words found in the question, when that is what decided it.
    matched: tuple[str, ...] = ()

    @property
    def searches_code(self) -> bool:
        return self.verdict == CODE


class ScopeGate:
    """
    The gate. One model call at most, and only for questions the codebase's own
    vocabulary cannot settle.

    Runs on the quality tier for the same reason `LLMQuestionPlanner` does — measured
    there, the fast tier anchored on one item of the offered list whatever was asked.
    The failure mode here is worse than a poor route: a small model that decides
    everything unfamiliar is off-topic turns a working feature into one that refuses
    its user. It is affordable because the shortcut means this call is not made for
    questions that name anything in the repository.
    """

    def __init__(self, profile: CodebaseProfile) -> None:
        self.profile = profile

    async def judge(self, question: str, history: list[dict] | None = None) -> ScopeVerdict:
        text = (question or "").strip()
        if not text:
            return ScopeVerdict(reason="nothing was asked")

        if matched := self.profile.mentions(text):
            return ScopeVerdict(
                reason=f"the question names {', '.join(matched)}",
                decided_by="vocabulary",
                matched=matched,
            )
        if _CODE_SHAPED.search(text):
            return ScopeVerdict(
                reason="the question names a file, a path, or something in backticks",
                decided_by="shape",
            )

        raw = await self._ask(text, history or [])
        if raw is None:
            # Fails open. A gate that refuses when the model is unreachable takes the
            # whole feature down with it, and does so silently.
            logger.info("scope_gate_unavailable", question=text[:80])
            return ScopeVerdict(reason="the gate could not be reached", decided_by="fallback")

        verdict = self._settle(raw)
        logger.info(
            "question_scoped",
            verdict=verdict.verdict,
            decided_by=verdict.decided_by,
            reason=verdict.reason[:120],
        )
        return verdict

    async def _ask(self, question: str, history: list[dict]) -> dict | None:
        from codelith.llm.client import chat_completion
        from codelith.llm.prompts.question_prompts import JUDGE_SCOPE
        from codelith.llm.router import select_spec

        messages = JUDGE_SCOPE.render(
            profile=self.profile.render(),
            history=_history(history) or "(this is the first question)",
            question=question,
        )
        try:
            raw = await chat_completion(messages, spec=select_spec("plan"), max_tokens=300)
        except JobCancelled:
            # Stopping is not a gate failure. Swallowing it here would answer the
            # question the reader just cancelled.
            raise
        except Exception as exc:
            logger.warning("scope_gate_call_failed", error=str(exc))
            return None

        try:
            parsed = json.loads(_extract_json(raw))
        except (json.JSONDecodeError, ValueError):
            logger.warning("scope_gate_unparseable", raw=(raw or "")[:200])
            return None
        return parsed if isinstance(parsed, dict) else None

    def _settle(self, raw: dict) -> ScopeVerdict:
        """
        The model proposes; this disposes — in one direction only.

        An unrecognised verdict answers `code`, as does a `code` verdict, as does
        anything malformed. Only an explicit, correctly spelled `chat` or `off_topic`
        stops the search, and even then a missing `reply` is filled in here rather
        than reaching the reader as an empty answer.
        """
        verdict = str(raw.get("verdict") or "").strip().lower()
        reason = str(raw.get("reason") or "").strip()[:200]
        if verdict not in _VERDICTS:
            logger.info("scope_gate_unknown_verdict", verdict=verdict[:40])
            return ScopeVerdict(
                reason=reason or "the gate did not answer clearly", decided_by="fallback"
            )
        if verdict == CODE:
            return ScopeVerdict(reason=reason, decided_by="llm")

        reply = str(raw.get("reply") or "").strip()[:800]
        return ScopeVerdict(
            verdict=verdict,
            reason=reason,
            reply=reply or self.decline(verdict),
            decided_by="llm",
        )

    def decline(self, verdict: str = OFF_TOPIC) -> str:
        """
        What to say when the model gave no reply of its own.

        Built from the profile rather than fixed, so it names the repository and
        offers something real to ask instead — a refusal that cannot say what *is*
        answerable reads as a broken feature rather than as a boundary.

        A greeting is not a refusal, so it does not get the refusing sentence. Both
        end the same way, because in both cases the useful half is the list.
        """
        name = self.profile.project_name
        line = (
            f"I answer questions about {name}, from what the analysis read."
            if verdict == CHAT
            else (
                f"That is not something I can answer from {name}. I only answer "
                "questions about this codebase, from what the analysis read."
            )
        )
        if self.profile.examples:
            offered = "\n".join(f"- {q}" for q in self.profile.examples[:3])
            return f"{line}\n\nThings it can answer:\n\n{offered}"
        return line


async def load_profile(db: AsyncSession, kb, project_name: str) -> CodebaseProfile:
    """
    Read the profile for one knowledge base.

    One query. The architecture map and the seeded questions are columns on the KB row
    the caller already holds, and only the overview narrative has to be fetched.
    """
    repos = KnowledgeRepositories.for_session(db)
    overview = await repos.narratives.get(kb.id, NarrativeTopic.OVERVIEW)
    return CodebaseProfile.build(
        project_name=project_name,
        architecture=kb.architecture_json,
        overview=overview.content_md if overview else "",
        suggestions=kb.suggested_questions_json,
    )


# ── Internals ─────────────────────────────────────────────────────────────────


def _stack(architecture: object) -> tuple[str, ...]:
    """The stack analysis found, flattened. Model output, so nothing is assumed."""
    if not isinstance(architecture, dict):
        return ()
    stack = architecture.get("tech_stack") or architecture.get("stack")
    if not isinstance(stack, dict):
        return ()

    out: list[str] = []
    for key in ("language", "frameworks", "databases", "infra"):
        value = stack.get(key)
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
        elif isinstance(value, list):
            out.extend(str(v).strip() for v in value if str(v).strip())
    return tuple(dict.fromkeys(out))[:15]


def _modules(architecture: object, found: list) -> tuple[str, ...]:
    """
    Module names, from the components first and the layers after.

    Components are the better source — they are named for what this system does — but
    a repository whose architecture pass named no components can still have layers,
    and a list of module names is a usable description of a codebase.
    """
    names: list[str] = []
    for component in found:
        names.extend(component.modules)
    if isinstance(architecture, dict):
        layers = architecture.get("layers")
        if isinstance(layers, list):
            for layer in layers:
                if isinstance(layer, dict) and isinstance(layer.get("modules"), list):
                    names.extend(str(m).strip() for m in layer["modules"] if str(m).strip())
    return tuple(dict.fromkeys(n for n in names if n))[:_MAX_MODULES]


def _terms(
    project_name: str, found: list, stack: tuple[str, ...], modules: tuple[str, ...]
) -> frozenset[str]:
    """
    The words that belong to this repository and not to repositories in general.

    Component *names* and not their descriptions: a description is a sentence of
    ordinary English, and taking its words would put "handles", "requests" and
    "stores" into the set that decides a question is about this codebase.

    Split and unsplit both, because a compound is asked about both ways. `FastAPI`
    yields `fast` and `api` when split — the first useless, the second too short to
    keep — so "does it use FastAPI" matched nothing at all until the whole word was
    kept alongside its parts.
    """
    words: set[str] = set()
    for text in (project_name, *(c.name for c in found), *stack, *modules):
        lowered = str(text).lower()
        words.update(_WORD.findall(lowered))
        words.update(_WORD.findall(_split_case(str(text)).lower()))
    return frozenset(w for w in words if len(w) >= 4 and w not in _GENERIC)


def _split_case(text: str) -> str:
    """`FaceTracking` → `Face Tracking`, so a compound name contributes both words."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)


def _first_prose(markdown: str) -> str:
    """
    The opening paragraph of the overview, without its heading.

    The whole narrative is several hundred lines about how the system works. What the
    gate needs is the sentence that says what it *is*.
    """
    for block in (markdown or "").split("\n\n"):
        text = block.strip()
        if text and not text.startswith("#"):
            return " ".join(text.split())
    return ""


def _history(history: list[dict]) -> str:
    """
    The last turns, oldest first, trimmed.

    This is the half of the gate a question-at-a-time classifier cannot have. "and
    France?" is about a country table or about nothing, and which one it is was
    settled two turns ago.
    """
    lines: list[str] = []
    for turn in history[-_HISTORY_TURNS:]:
        content = " ".join(str(turn.get("content") or "").split())
        if not content:
            continue
        role = "Asked" if turn.get("role") == "user" else "Answered"
        lines.append(f"{role}: {content[:_HISTORY_CHARS]}")
    return "\n".join(lines)


def _extract_json(raw: str) -> str:
    """Strip fences and surrounding prose. Mirrors `questions._extract_json`."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    if "```" in raw:
        raw = raw.split("```")[0]
    if match := re.search(r"[{\[]", raw):
        start = match.start()
        end = max(raw.rfind("}"), raw.rfind("]")) + 1
        if end > start:
            raw = raw[start:end]
    return raw.strip()


__all__ = [
    "CHAT",
    "CODE",
    "OFF_TOPIC",
    "CodebaseProfile",
    "ScopeGate",
    "ScopeVerdict",
    "load_profile",
]
