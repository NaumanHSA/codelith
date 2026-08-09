"""
Answering a question about a codebase.

The retrieval half of this is K4 and was measured before anything was built on it:
`QuestionRouter.gather()` routes a question with a model, validates every field it
returns against the knowledge base, and comes back with ranked evidence carrying
provenance. This adds the other half — a prompt, a stream, and a check.

**The check is the point.** Every citation in the answer is verified against the
evidence actually retrieved, and one that does not resolve is stripped. This is the
same rule the router follows: the model proposes and the knowledge base disposes. A
chat that *sounds* grounded is worse than one that obviously guesses, because the
reader has no means of telling them apart.

One retrieval pass, one answer. No agentic loop — an agent that re-queries until
satisfied is a larger thing, and this should be measured before anything cleverer is
built on top of it.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.knowledge.constants import KBStatus
from app.knowledge.questions import EvidenceBundle, QuestionRouter
from app.knowledge.tools import TOOL_SCHEMAS, CodebaseTools
from app.llm.client import ToolsUnsupported, stream_completion, stream_tool_completion
from app.llm.context_manager import count_text_tokens
from app.llm.prompts.answer_prompts import ANSWER_QUESTION
from app.llm.router import select_spec
from app.models.knowledge import KnowledgeBase

logger = structlog.get_logger(__name__)

#: `app/db/session.py:12-40`, with or without backticks, with or without lines.
#:
#: Bare paths have to match. Asked to cite in backticks, a real answer wrote
#: `neurosurfer/vectorstores/chroma.py:13-105` as plain prose — every citation in it
#: was correct and every one went unchecked, because the pattern required a
#: formatting convention the model had not followed. Depending on a model to format
#: its output for a safety check is depending on it not to make the mistake the check
#: exists to catch.
#:
#: Two shapes, with different strictness. Inside backticks the writer has already
#: marked the token as code, so a bare filename counts. Outside them a slash is
#: required — otherwise "e.g." and "i.e." are citations, and prose is full of them.
#: A citation names a *file*, so the suffix has to be a file extension. Matching any
#: short word after a dot made `neurosurfer.app.server` a citation with the extension
#: `.server` — and dotted module paths and `Class.method` references are how a model
#: naturally writes about Python. Measured on one run: 22 of 22 "invented" citations
#: were module names and function names, not files. The check was crying wolf, which
#: is worse than not checking, because it teaches a reader to ignore the warning.
_FILE_SUFFIX = (
    r"(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|go|java|rb|rs|php|kt|cs|c|h|cpp|hpp|swift|scala"
    r"|md|mdx|rst|txt|json|ya?ml|toml|ini|cfg|env|sh|bash|sql|html|css|scss|tf|lock)"
)

_CITATION = re.compile(
    rf"`(?P<quoted>[\w.-]+(?:/[\w.-]+)*\.{_FILE_SUFFIX}(?::\d+(?:-\d+)?)?)`"
    rf"|(?P<bare>(?:[\w.-]+/)+[\w.-]+\.{_FILE_SUFFIX}(?::\d+(?:-\d+)?)?)",
    re.I,
)

#: Fenced blocks are samples, not claims. A path inside one is part of the code being
#: shown, and rewriting it would edit the reader's example.
_FENCE_SPLIT = re.compile(r"(```.*?```)", re.S)

#: Turns of history handed to the model. The panel is one conversation about one
#: codebase, so this is short by construction; the cap only stops a long session
#: quietly growing the prompt without bound.
_MAX_HISTORY_TURNS = 8

#: Share of the context window the evidence and history may occupy between them.
#: The rest is the model's room to answer in — a prompt that fills the window leaves
#: nothing to reply with, which surfaces as a truncated answer rather than an error.
_PROMPT_SHARE = 0.6

#: Tool turns before the loop is cut off. Six is already a lot of looking; twenty is
#: a runaway that bills for itself and still answers late.
_MAX_TOOL_CALLS = 6

#: Ceiling on one tool result in the transcript. A file read that returns forty
#: thousand characters crowds out the evidence the question started from.
_TOOL_RESULT_CHARS = 6000


@dataclass(slots=True)
class Answer:
    """A finished answer and everything needed to judge it."""

    text: str = ""
    #: Citations that resolved against retrieved evidence.
    citations: list[str] = field(default_factory=list)
    #: Citations the model produced that did not resolve, and were removed.
    stripped: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    answer_tokens: int = 0
    evidence_count: int = 0


class AskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def stream(
        self,
        project,
        question: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        """
        Retrieve, then answer, emitting events as it goes.

        Events: `evidence` once retrieval is done, `token` per delta, `usage` and
        `done` at the end. The evidence event lands first on purpose — it gives the
        reader something true to look at during the seconds before the first token,
        and it is the part they can check.
        """
        question = (question or "").strip()
        if not question:
            raise ValidationError("Ask something — an empty question has no answer.")

        kb = await self._usable_kb(project.id)
        router = QuestionRouter(self.db, kb.id, project.id, project_name=project.name)
        bundle = await router.gather(question)

        yield {
            "type": "evidence",
            "counts": bundle.counts,
            "intents": bundle.plan.intents,
            "routed_by": bundle.plan.routed_by,
            "sources": self._sources(bundle),
        }

        messages, prompt_tokens = self._prompt(project, question, bundle, history or [])
        spec = select_spec("write")

        # Answer and escalation are the same call. The model is given tools alongside
        # the evidence: if it answers, that answer streamed; if it reaches for a tool,
        # nothing was shown and the loop continues. Deciding separately cost a full
        # round-trip on every question to hear "no" — measured, it doubled the time
        # of questions that made no tool calls at all.
        chunks: list[str] = []
        async for event in self._answer(messages, bundle, kb.id, project.id, spec):
            if event["type"] == "token":
                chunks.append(event["text"])
            elif event["type"] == "reset":
                # The model spoke before reaching for a tool. What it said was a
                # preamble to looking, not the answer.
                chunks.clear()
            yield event

        answer = self._finish("".join(chunks), bundle, prompt_tokens)
        yield {
            "type": "usage",
            "prompt_tokens": answer.prompt_tokens,
            "answer_tokens": answer.answer_tokens,
            "context_window": spec.context_window,
        }
        yield {
            "type": "done",
            "text": answer.text,
            "citations": answer.citations,
            "stripped": answer.stripped,
        }

        logger.info(
            "question_answered",
            project_id=project.id,
            evidence=answer.evidence_count,
            citations=len(answer.citations),
            stripped=len(answer.stripped),
        )

    async def _answer(
        self,
        messages: list[dict],
        bundle: EvidenceBundle,
        kb_id: int,
        project_id: int,
        spec,
    ):
        """
        Stream the answer, looking further if the model asks to.

        One retrieval pass answers most questions — measured on the twenty-question
        set, fourteen answered without hedging, and two of the six that hedged were
        true absences. So roughly one in five wanted a second look.

        **Answering and escalating are the same call.** The model gets the evidence
        and the tools together: reaching for a tool *is* the escalation signal, and a
        turn that does not reach for one has already streamed the answer. An earlier
        version asked separately and paid a full round-trip on every question to hear
        "no" — "what endpoints does it expose" went from 18s to 45s having made no
        tool calls at all.

        Everything a tool returns is appended to the prompt and to the bundle, so the
        citation check covers it exactly like pre-loaded evidence.
        """
        tools = CodebaseTools(self.db, kb_id, project_id)
        working = list(messages)
        used = 0

        while True:
            spoke = False
            calls: list[dict] = []

            try:
                async for frame in stream_tool_completion(
                    working, TOOL_SCHEMAS, spec=spec
                ):
                    if "delta" in frame:
                        spoke = True
                        yield {"type": "token", "text": frame["delta"]}
                    else:
                        calls = frame["tool_calls"]
            except ToolsUnsupported as exc:
                # Small local models refuse tool definitions outright. Answering from
                # the evidence already in the prompt is why it is pre-loaded.
                logger.info("ask_tools_unsupported", error=str(exc))
                async for delta in stream_completion(working, spec=spec):
                    yield {"type": "token", "text": delta}
                return

            if not calls:
                return

            if spoke:
                # It talked before reaching for a tool. That was thinking aloud, not
                # the answer — the reader should not keep it.
                yield {"type": "reset"}

            if used >= _MAX_TOOL_CALLS:
                # Out of budget. Answer from what has been gathered rather than
                # leaving the reader with a half-finished search.
                logger.info("ask_tool_budget_spent", calls=used)
                working.append({
                    "role": "user",
                    "content": (
                        "You have looked far enough. Answer now from everything above, "
                        "and say plainly what remains unsettled."
                    ),
                })
                async for delta in stream_completion(working, spec=spec):
                    yield {"type": "token", "text": delta}
                return

            working.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in calls
                ],
            })

            for call in calls:
                used += 1
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                yield {"type": "tool", "name": call["name"], "args": args, "step": used}

                text, found = await tools.run(call["name"], args)
                bundle.items.extend(found)
                working.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": text[:_TOOL_RESULT_CHARS],
                })

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _usable_kb(self, project_id: int) -> KnowledgeBase:
        """
        The knowledge base to answer from, or a message saying why there is none.

        A project that has never been analysed cannot be asked about, and saying so
        is far more use than an answer assembled from nothing.
        """
        kb = (
            await self.db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.project_id == project_id)
                .order_by(KnowledgeBase.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if kb is None:
            raise ValidationError(
                "This project has not been analysed yet, so there is nothing to ask "
                "about. Run an analysis first."
            )
        if kb.status not in (KBStatus.READY, KBStatus.STALE, KBStatus.DEGRADED):
            raise ValidationError(
                f"This project's knowledge base is {kb.status}. Wait for the analysis "
                "to finish, or run it again."
            )
        return kb

    def _prompt(
        self, project, question: str, bundle: EvidenceBundle, history: list[dict]
    ) -> tuple[list[dict], int]:
        """
        The messages, and what they cost.

        History is trimmed before evidence, always. Evidence is what makes an answer
        grounded; earlier turns are context a reader can restate. Dropping evidence
        first would produce an answer that reads fluently and cites nothing.
        """
        spec = select_spec("write")
        budget = int(spec.context_window * _PROMPT_SHARE)

        evidence = bundle.render()
        rendered_history = self._history(history, budget - count_text_tokens(evidence))

        messages = ANSWER_QUESTION.render(
            project_name=project.name,
            question=question,
            evidence=evidence or "(nothing was retrieved for this question)",
            history=rendered_history,
        )
        return messages, count_text_tokens("\n".join(m["content"] for m in messages))

    @staticmethod
    def _history(history: list[dict], budget: int) -> str:
        """Earlier turns, newest first until the budget runs out."""
        if not history or budget <= 0:
            return ""

        kept: list[str] = []
        used = 0
        for turn in reversed(history[-_MAX_HISTORY_TURNS:]):
            role = "You asked" if turn.get("role") == "user" else "You answered"
            line = f"{role}: {(turn.get('content') or '').strip()}"
            cost = count_text_tokens(line)
            if used + cost > budget:
                break
            kept.append(line)
            used += cost

        if not kept:
            return ""
        return "\n## Earlier in this conversation\n\n" + "\n\n".join(reversed(kept)) + "\n"

    def _finish(self, text: str, bundle: EvidenceBundle, prompt_tokens: int) -> Answer:
        kept, stripped, cleaned = self._check_citations(text, bundle)
        return Answer(
            text=cleaned,
            citations=kept,
            stripped=stripped,
            prompt_tokens=prompt_tokens,
            answer_tokens=count_text_tokens(text),
            evidence_count=len(bundle.items),
        )

    @staticmethod
    def _check_citations(text: str, bundle: EvidenceBundle) -> tuple[list[str], list[str], str]:
        """
        Keep the citations that resolve; strip the ones that do not.

        A model asked to cite will produce a plausible `app/services/handler.py:40-60`
        for a file that does not exist, and it is indistinguishable from a real one to
        anybody who has not memorised the repository. The line range is not checked —
        a citation off by a few lines still points the reader at the right file, and
        rejecting it would remove a working reference over a rounding error.

        A citation that resolves is *normalised into backticks* whether or not the
        model wrote them, so the studio can render every verified reference as a chip
        without depending on the model's formatting. One that does not resolve loses
        them: the sentence around it still reads, and the missing backticks are the
        signal that it could not be checked.

        Fenced blocks are skipped entirely — a path inside a code sample is part of
        the example, not a claim about the repository.
        """
        known = {p for p in _paths_in(bundle) if p}

        kept: list[str] = []
        stripped: list[str] = []

        def resolves(path: str) -> bool:
            if path in known:
                return True
            return any(
                k.endswith(f"/{path}") or path.endswith(f"/{k}") for k in known if k
            )

        def replace(match: re.Match[str]) -> str:
            citation = match.group("quoted") or match.group("bare")
            path = citation.split(":", 1)[0]
            if resolves(path):
                if citation not in kept:
                    kept.append(citation)
                return f"`{citation}`"
            if citation not in stripped:
                stripped.append(citation)
            return citation

        # Only the prose between fences is scanned. `re.split` with a capturing group
        # keeps the fences themselves in the list, so they pass through untouched.
        parts = _FENCE_SPLIT.split(text)
        for index, part in enumerate(parts):
            if not part.startswith("```"):
                parts[index] = _CITATION.sub(replace, part)

        return kept, stripped, "".join(parts)

    @staticmethod
    def _sources(bundle: EvidenceBundle) -> list[dict]:
        """What the answer was built from, for the reader to open."""
        return [
            {"kind": item.kind, "title": item.title, "why": item.why}
            for item in bundle.items[:40]
        ]


#: A repository path inside a block of evidence.
_PATH_IN_TEXT = re.compile(rf"(?:[\w.-]+/)+[\w.-]+\.{_FILE_SUFFIX}", re.I)


def _with_extra_evidence(prompt: str, fetched: list) -> str:
    """
    Put what the loop found in front of the model, above the question.

    Appending it after the question would make the newest evidence the thing the
    model reads last and weights least — the opposite of what it went looking for.
    """
    blocks = "\n\n".join(f"--- {e.title} ---\n{e.body}" for e in fetched)
    section = f"\n## Also found while looking further\n\n{blocks}\n\n"
    if "## Question" in prompt:
        return prompt.replace("## Question", f"{section}## Question", 1)
    return prompt + section


def _paths_in(bundle: EvidenceBundle) -> set[str]:
    """
    Every file path the evidence names, from titles *and* bodies.

    Bodies matter and it is not obvious why. A code block is titled with its path,
    but an entity is titled `datastore: Chroma` and carries `at
    neurosurfer/vectorstores/chroma.py:16` in the body. Reading titles alone, a
    perfectly good citation to a file the evidence had just named was being stripped
    as an invention — measured on a real answer, two of three "inventions" were this.
    """
    out: set[str] = set()
    for item in bundle.items:
        head = item.title.split(":")[0].strip().lstrip("- ").strip()
        if head:
            out.add(head)
            out.add(head.rsplit("/", 1)[-1])
        for match in _PATH_IN_TEXT.finditer(item.body or ""):
            path = match.group(0)
            out.add(path)
            out.add(path.rsplit("/", 1)[-1])
    return out


__all__ = ["AskService", "Answer"]
