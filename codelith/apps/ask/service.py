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

**Not every question goes to the code.** `ScopeGate` runs first and can answer
"none of the stores" — the one thing the router structurally cannot say, because
everything handed to it is routed. Asked for the capital of France it used to return
the three chunks whose embeddings sat closest to a country, and answer from them, in
the same confident voice it uses for a real citation. See
`codelith/knowledge/scope.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.config import get_settings
from codelith.core.cancellation import JobCancelled
from codelith.core.exceptions import ValidationError
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.questions import EvidenceBundle, QuestionRouter
from codelith.knowledge.scope import ScopeGate, ScopeVerdict, load_profile
from codelith.knowledge.tools import TOOL_SCHEMAS, CodebaseTools
from codelith.llm.client import ToolsUnsupported, stream_completion, stream_tool_completion
from codelith.llm.context_manager import count_text_tokens
from codelith.llm.prompts.answer_prompts import ANSWER_QUESTION
from codelith.llm.router import select_spec
from codelith.models.knowledge import KnowledgeBase

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

#: The extension has to be the *whole* extension. Alternation is first-match-wins, so
#: `js` matched inside `mcp.json` and the citation became `.neurosurfer/mcp.js` — a
#: file that does not exist, duly reported to the reader as an invention. The same
#: trap sits under `ts`/`tsx`, `md`/`mdx` and `c`/`cpp`. Rather than depend on the
#: list staying sorted longest-first, require that nothing word-like follows.
_ENDS = r"(?![A-Za-z0-9])"

_CITATION = re.compile(
    rf"`(?P<quoted>[\w.-]+(?:/[\w.-]+)*\.{_FILE_SUFFIX}{_ENDS}(?::\d+(?:-\d+)?)?)`"
    rf"|(?P<bare>(?:[\w.-]+/)+[\w.-]+\.{_FILE_SUFFIX}{_ENDS}(?::\d+(?:-\d+)?)?)",
    re.I,
)

#: Fenced blocks are samples, not claims. A path inside one is part of the code being
#: shown, and rewriting it would edit the reader's example.
_FENCE_SPLIT = re.compile(r"(```.*?```)", re.S)


def _fence_label(block: str) -> str:
    """
    The attribution line of a fenced block, if it has one.

    The first line inside a fence is where a model says where the sample came from —
    `# routes_chat.py:8-73`. Only that line, and only when it is a comment: a fence
    whose first line is code is a sample all the way down.
    """
    lines = block.split("\n", 2)
    if len(lines) < 2:
        return ""
    first = lines[1].strip()
    return first if first.startswith(("#", "//", "--", "<!--", "/*", "*")) else ""

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

#: Share of the context window all tool results together may occupy.
#:
#: Capping each result and not the total is a cap that does not cap. Six results at
#: `_TOOL_RESULT_CHARS` is 36,000 characters — roughly 9,000 tokens — landing on top
#: of a prompt already built to `_PROMPT_SHARE` of the window. On a 32k model that
#: leaves the answer no room, and the failure is silent: the model returns an empty
#: message with `finish_reason: stop`, not an error. Measured, that is exactly what
#: the one unrecoverable blank answer was doing, six tool calls deep.
#:
#: 0.6 + 0.15 leaves a quarter of the window to answer in.
_TOOL_SHARE = 0.15


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
        Judge, retrieve, then answer, emitting events as it goes.

        Events: `scope` once the question has been judged, `evidence` once retrieval
        is done, `token` per delta, `usage` and `done` at the end. The evidence event
        lands early on purpose — it gives the reader something true to look at during
        the seconds before the first token, and it is the part they can check.

        A question the gate does not send to the code produces `scope` and then the
        answer, with no `evidence` event between them. That absence is the honest
        shape of what happened: nothing was retrieved, so there is nothing to show.
        """
        question = (question or "").strip()
        if not question:
            raise ValidationError("Ask something — an empty question has no answer.")

        kb = await self._usable_kb(project.id)

        verdict = await self._scope(project, kb, question, history or [])
        yield {
            "type": "scope",
            "verdict": verdict.verdict,
            "reason": verdict.reason,
            "decided_by": verdict.decided_by,
        }
        if not verdict.searches_code:
            logger.info(
                "question_not_searched",
                project_id=project.id,
                verdict=verdict.verdict,
                decided_by=verdict.decided_by,
            )
            for event in self._without_searching(verdict):
                yield event
            return

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
        room = self._tool_budget(spec)

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
                if spoke:
                    return
                # Neither an answer nor a tool call: the turn said nothing at all.
                # Measured against a local reasoning model, this is what a turn *after
                # a tool result* often looks like — it thinks for a few hundred
                # characters, stops with `finish_reason: stop`, and streams no content.
                # Five of twenty questions came back blank that way, and the reader saw
                # an empty message with no indication anything had gone wrong.
                #
                # Asking again without tools is what breaks it: the transcript already
                # holds the evidence and every tool result, so there is a real answer
                # to give, and removing the tools removes the option of reaching for
                # another one instead of replying.
                logger.info("ask_turn_said_nothing", tool_calls_used=used)
                async for delta in self._answer_now(working, spec):
                    yield {"type": "token", "text": delta}
                return

            if spoke:
                # It talked before reaching for a tool. That was thinking aloud, not
                # the answer — the reader should not keep it.
                yield {"type": "reset"}

            if used >= _MAX_TOOL_CALLS or room <= 0:
                # Out of budget — of steps, or of room in the window to put another
                # result. Answer from what has been gathered rather than leaving the
                # reader with a half-finished search.
                logger.info("ask_tool_budget_spent", calls=used, room_left=room)
                async for delta in self._answer_now(working, spec):
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

                # Trimmed against what is left of the window, not just against the
                # per-result cap. The evidence itself is unaffected — `found` already
                # joined the bundle in full, so a citation to something trimmed out of
                # the transcript still resolves.
                content = text[:_TOOL_RESULT_CHARS]
                if (cost := count_text_tokens(content)) > room:
                    content = content[: max(0, room) * 4]
                    if content:
                        content += "\n\n[trimmed — the context window is full]"
                    cost = count_text_tokens(content)
                room -= cost

                working.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": content or "[no room left in the context window]",
                })

                if room <= 0:
                    # Stop pulling results the model has no room to read. Breaking
                    # here rather than looping means the next turn is the answer.
                    logger.info("ask_tool_window_full", calls=used)
                    break

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    async def _answer_now(working: list[dict], spec) -> AsyncIterator[str]:
        """
        Ask for the answer, without tools and with something to answer.

        The nudge is not politeness. A transcript that ends on a tool result gives the
        model nothing to reply *to*, and measured against a local reasoning model that
        is what a blank answer looks like: it reads the result, thinks for a couple of
        hundred characters, and stops with `finish_reason: stop` and no content. Ending
        on a user turn asks a question, so there is an answer to give.

        Tools are withheld deliberately — offering them here is offering the option of
        looking again instead of replying, which is the behaviour being recovered from.
        """
        return_now = list(working)
        return_now.append({
            "role": "user",
            "content": (
                "You have looked far enough. Answer the question now from everything "
                "above, and say plainly what remains unsettled."
            ),
        })
        async for delta in stream_completion(return_now, spec=spec):
            yield delta

    @staticmethod
    def _tool_budget(spec) -> int:
        """Tokens all tool results together may add to the transcript."""
        window = getattr(spec, "context_window", None) or 32_768
        return int(window * _TOOL_SHARE)

    async def _scope(
        self, project, kb: KnowledgeBase, question: str, history: list[dict]
    ) -> ScopeVerdict:
        """
        Whether this question is about this codebase, before anything is searched.

        Behind a setting rather than behind an edit to this file: the gate's one bad
        outcome is a real question declined, that judgement is made by whichever
        model the reader is running locally, and somebody who does not trust theirs
        with it needs a way to switch it off that is not a release.

        Any failure here answers "search the code" — including a failure to read the
        profile, which is a database call and can go wrong for reasons that have
        nothing to do with the question. The gate exists to improve a working
        feature, and it must never be the reason one stops working.
        """
        if not get_settings().ASK_SCOPE_GATE:
            return ScopeVerdict(decided_by="disabled", reason="the scope gate is switched off")
        try:
            profile = await load_profile(self.db, kb, project.name)
        except JobCancelled:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("scope_profile_unavailable", error=str(exc))
            return ScopeVerdict(decided_by="fallback", reason="the profile could not be read")
        return await ScopeGate(profile).judge(question, history)

    def _without_searching(self, verdict: ScopeVerdict) -> list[dict]:
        """
        The events for a question that was not sent to the code.

        The reply was written by the gate in the same call that judged the question,
        so nothing more is spent here: a second call to produce one sentence would
        make the questions that least deserve it the slowest to come back. It is one
        `token` event, so the studio renders it down the path it renders every other
        answer, and `done` carries no citations because nothing was retrieved to
        cite.
        """
        text = verdict.reply
        return [
            {"type": "token", "text": text},
            {
                "type": "usage",
                "prompt_tokens": 0,
                "answer_tokens": count_text_tokens(text),
                "context_window": select_spec("write").context_window,
            },
            {"type": "done", "text": text, "citations": [], "stripped": []},
        ]

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
        if not KBStatus(kb.status).can_serve_features:
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

        Fenced blocks are skipped — a path inside a code sample is part of the
        example, not a claim about the repository. **Except its first line**, which by
        overwhelming convention is where a model labels the sample with where it came
        from:

            ```python
            # routes_chat.py:8-73
            @router.post("/v1/chat/completions")

        That is a citation by any reading, and skipping it was expensive: measured
        across twenty answers, seventeen citations were sitting in fence labels, and
        two of the three answers that appeared to cite *nothing at all* had three and
        four of them. They were being penalised for showing their work.

        A label that resolves is counted. One that does not is reported but left
        alone: rewriting inside a fence would edit the sample the reader is looking at,
        and stripping backticks there is invisible anyway.
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
            if part.startswith("```"):
                for match in _CITATION.finditer(_fence_label(part)):
                    citation = match.group("quoted") or match.group("bare")
                    target = kept if resolves(citation.split(":", 1)[0]) else stripped
                    if citation not in target:
                        target.append(citation)
            else:
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
