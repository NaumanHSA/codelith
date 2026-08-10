"""
Looking further, and knowing when not to.

Q1–Q6 answered in a straight line. That works when the answer exists somewhere as
text and fails when it has to be assembled — measured on the twenty-question set, six
of twenty said the evidence was insufficient.

The design that matters is that **answering and escalating are the same call**. The
model gets evidence and tools together: reaching for a tool is the escalation signal,
and a turn that does not reach for one has already streamed the answer.

An earlier version asked separately, and it was expensive in exactly the wrong place:
"what endpoints does it expose" went from 18s to 45s *having made no tool calls at
all*. Every question paid a round-trip to hear "no". These cases exist mostly to keep
that from coming back.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.llm.client import ToolsUnsupported
from codelith.apps.ask import service as ask_service
from codelith.apps.ask.service import AskService
from codelith.knowledge.questions import Evidence, EvidenceBundle, QuestionPlan


def _bundle() -> EvidenceBundle:
    bundle = EvidenceBundle(plan=QuestionPlan(question="q"))
    bundle.items = [
        Evidence(kind="code", title="app/db/session.py:1-20", body="…", why="match")
    ]
    return bundle


def _messages() -> list[dict]:
    return [
        {"role": "system", "content": "answer questions"},
        {"role": "user", "content": "## Evidence\n\nx\n\n## Question\n\nhow?"},
    ]


def _turn(*, deltas: list[str] | None = None, calls: list[dict] | None = None):
    """One scripted turn of `stream_tool_completion`."""
    return {"deltas": deltas or [], "calls": calls or []}


@pytest.fixture
def scripted(monkeypatch):
    """Drives `_answer` through a fixed sequence of model turns."""

    def _install(turns: list[dict], tool_result: str = "found it"):
        state = {"turn": 0, "tool_calls": [], "final_stream": 0}

        async def fake_stream_tool_completion(messages, tools, spec=None, **kwargs):
            script = turns[min(state["turn"], len(turns) - 1)]
            state["turn"] += 1
            for delta in script["deltas"]:
                yield {"delta": delta}
            yield {"tool_calls": script["calls"]}

        async def fake_stream_completion(messages, spec=None, **kwargs):
            state["final_stream"] += 1
            yield "fallback answer"

        class _Tools:
            def __init__(self, *a, **k):
                pass

            async def run(self, name, args):
                state["tool_calls"].append((name, args))
                return tool_result, [
                    Evidence(kind="code", title="app/found.py:1-9", body="x", why=name)
                ]

        monkeypatch.setattr(ask_service, "stream_tool_completion", fake_stream_tool_completion)
        monkeypatch.setattr(ask_service, "stream_completion", fake_stream_completion)
        monkeypatch.setattr(ask_service, "CodebaseTools", _Tools)
        return state

    return _install


async def _collect(service, messages, bundle):
    return [e async for e in service._answer(messages, bundle, kb_id=1, project_id=1, spec=None)]


async def _collect_with(service, spec):
    return [
        e
        async for e in service._answer(
            _messages(), _bundle(), kb_id=1, project_id=1, spec=spec
        )
    ]


class TestTheCommonCaseCostsNothing:
    async def test_an_answer_streams_without_a_second_call(self, scripted) -> None:
        """The whole reason the turn is streamed. If this regresses, every question
        pays a round-trip to be told no tool was needed."""
        state = scripted([_turn(deltas=["The ", "answer."])])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert [e["text"] for e in events if e["type"] == "token"] == ["The ", "answer."]
        assert state["turn"] == 1
        assert state["tool_calls"] == []

    async def test_no_reset_is_emitted_when_nothing_was_discarded(self, scripted) -> None:
        scripted([_turn(deltas=["done"])])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert not any(e["type"] == "reset" for e in events)


class TestEscalation:
    async def test_a_tool_call_runs_and_the_loop_continues(self, scripted) -> None:
        state = scripted([
            _turn(calls=[{"id": "1", "name": "read_file", "arguments": '{"path": "app/x.py"}'}]),
            _turn(deltas=["Now I know."]),
        ])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert state["tool_calls"] == [("read_file", {"path": "app/x.py"})]
        assert [e["text"] for e in events if e["type"] == "token"] == ["Now I know."]

    async def test_the_reader_is_told_what_it_is_looking_at(self, scripted) -> None:
        """The wait is longer when it escalates, so it has to be legible."""
        scripted([
            _turn(calls=[{"id": "1", "name": "find_callers", "arguments": '{"symbol": "run"}'}]),
            _turn(deltas=["ok"]),
        ])

        events = await _collect(AskService(None), _messages(), _bundle())
        tool_events = [e for e in events if e["type"] == "tool"]

        assert tool_events[0]["name"] == "find_callers"
        assert tool_events[0]["args"] == {"symbol": "run"}
        assert tool_events[0]["step"] == 1

    async def test_what_a_tool_found_joins_the_evidence(self, scripted) -> None:
        """So a citation to something the loop fetched resolves exactly like one to
        pre-loaded evidence. The safety property does not change; the pool grows."""
        scripted([
            _turn(calls=[{"id": "1", "name": "read_file", "arguments": '{"path": "app/x.py"}'}]),
            _turn(deltas=["ok"]),
        ])
        bundle = _bundle()

        await _collect(AskService(None), _messages(), bundle)

        assert "app/found.py:1-9" in {i.title for i in bundle.items}

    async def test_a_preamble_before_a_tool_call_is_discarded(self, scripted) -> None:
        """A model that says "let me check the session module" and then reaches for a
        tool was thinking aloud. The reader should not keep it as the answer."""
        scripted([
            _turn(
                deltas=["Let me look at that."],
                calls=[{"id": "1", "name": "read_file", "arguments": "{}"}],
            ),
            _turn(deltas=["The real answer."]),
        ])

        events = await _collect(AskService(None), _messages(), _bundle())
        kinds = [e["type"] for e in events]

        assert "reset" in kinds
        assert kinds.index("reset") < kinds.index("tool")

    async def test_malformed_arguments_do_not_break_the_loop(self, scripted) -> None:
        state = scripted([
            _turn(calls=[{"id": "1", "name": "read_file", "arguments": "{not json"}]),
            _turn(deltas=["ok"]),
        ])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert state["tool_calls"] == [("read_file", {})]
        assert any(e["type"] == "token" for e in events)


class TestASilentTurn:
    """
    A turn that streams neither content nor a tool call.

    Measured against a local reasoning model, this is what a turn *after a tool
    result* often looks like: a few hundred characters of reasoning, then
    `finish_reason: stop` and no content at all. Five of twenty questions came back
    blank that way, and the run harness reported every one of them as "ok" — the
    reader would have seen an empty message with nothing to indicate a problem.
    """

    async def test_an_empty_turn_is_retried_without_tools(self, scripted) -> None:
        state = scripted([
            _turn(calls=[{"id": "1", "name": "read_file", "arguments": '{"path": "a.py"}'}]),
            _turn(),  # thought, then said nothing
        ])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert [e["text"] for e in events if e["type"] == "token"] == ["fallback answer"]
        assert state["final_stream"] == 1

    async def test_the_retry_keeps_what_the_tools_found(
        self, scripted, monkeypatch
    ) -> None:
        """Retrying from the original prompt would throw away the lookup that was
        just paid for, and re-ask a question the transcript can already answer."""
        seen: dict = {}
        scripted([
            _turn(calls=[{"id": "1", "name": "read_file", "arguments": "{}"}]),
            _turn(),
        ])

        async def capture(messages, spec=None, **kwargs):
            seen["messages"] = messages
            yield "fallback answer"

        monkeypatch.setattr(ask_service, "stream_completion", capture)

        await _collect(AskService(None), _messages(), _bundle())

        assert "tool" in [m["role"] for m in seen["messages"]], (
            "the tool result must survive into the retry"
        )

    async def test_the_retry_ends_on_a_question(self, scripted, monkeypatch) -> None:
        """A transcript ending on a tool result gives the model nothing to reply to,
        and measured, that is what it does — it reads the result and stops. Two of the
        five blank answers survived a retry that just replayed the transcript."""
        seen: dict = {}
        scripted([
            _turn(calls=[{"id": "1", "name": "read_file", "arguments": "{}"}]),
            _turn(),
        ])

        async def capture(messages, spec=None, **kwargs):
            seen["messages"] = messages
            yield "fallback answer"

        monkeypatch.setattr(ask_service, "stream_completion", capture)

        await _collect(AskService(None), _messages(), _bundle())

        assert seen["messages"][-1]["role"] == "user"
        assert "Answer the question now" in seen["messages"][-1]["content"]

    async def test_the_retry_does_not_mutate_the_transcript(
        self, scripted, monkeypatch
    ) -> None:
        """The nudge is scaffolding for one call, not part of the conversation."""
        seen: list = []
        scripted([_turn()])

        async def capture(messages, spec=None, **kwargs):
            seen.append(messages)
            yield "x"

        monkeypatch.setattr(ask_service, "stream_completion", capture)
        original = _messages()

        await _collect(AskService(None), original, _bundle())

        assert len(original) == 2, "the caller's messages were appended to"

    async def test_an_empty_first_turn_is_also_retried(self, scripted) -> None:
        """No tool call and nothing said on the very first turn. The evidence is
        already in the prompt, so there is a real answer to give."""
        state = scripted([_turn()])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert [e["text"] for e in events if e["type"] == "token"] == ["fallback answer"]
        assert state["tool_calls"] == []

    async def test_a_turn_that_spoke_is_not_retried(self, scripted) -> None:
        """The guard above must not fire on the common path — that would double the
        cost of every question that answered first time."""
        state = scripted([_turn(deltas=["A real answer."])])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert [e["text"] for e in events if e["type"] == "token"] == ["A real answer."]
        assert state["final_stream"] == 0


class TestTheWindowIsABudgetToo:
    """
    Capping each tool result and not the total is a cap that does not cap.

    Six results at `_TOOL_RESULT_CHARS` is ~9,000 tokens landing on a prompt already
    built to `_PROMPT_SHARE` of the window. On a 32k model that leaves nothing to
    answer in, and the failure is silent — an empty message with `finish_reason:
    stop`, not an error. That is what the one blank answer that survived the
    silent-turn retry was doing, six tool calls deep.
    """

    async def test_results_are_trimmed_to_what_is_left(self, scripted) -> None:
        spec = SimpleNamespace(context_window=2_000)  # budget: 300 tokens
        scripted(
            [
                _turn(calls=[{"id": "1", "name": "read_file", "arguments": "{}"}]),
                _turn(deltas=["answer"]),
            ],
            tool_result="x " * 20_000,
        )

        events = [
            e
            async for e in AskService(None)._answer(
                _messages(), _bundle(), kb_id=1, project_id=1, spec=spec
            )
        ]

        assert any(e["type"] == "token" for e in events)

    async def test_a_full_window_stops_the_loop(self, scripted) -> None:
        """Pulling results the model has no room to read is paying for nothing."""
        spec = SimpleNamespace(context_window=2_000)
        state = scripted(
            [_turn(calls=[{"id": "1", "name": "search_code", "arguments": '{"query": "x"}'}])],
            tool_result="y " * 20_000,
        )

        await _collect_with(AskService(None), spec)

        assert len(state["tool_calls"]) < ask_service._MAX_TOOL_CALLS, (
            "the step budget should not be what stops it — the window should"
        )

    async def test_a_generous_window_does_not_trim(self, scripted) -> None:
        """The guard must not fire on ordinary questions, or every escalation loses
        the evidence it just paid to fetch."""
        spec = SimpleNamespace(context_window=200_000)
        state = scripted(
            [
                _turn(calls=[{"id": "1", "name": "read_file", "arguments": "{}"}]),
                _turn(deltas=["ok"]),
            ],
            tool_result="z " * 100,
        )

        await _collect_with(AskService(None), spec)

        assert len(state["tool_calls"]) == 1


class TestBudget:
    async def test_a_model_that_never_stops_is_cut_off(self, scripted) -> None:
        """Six calls is a lot of looking. Twenty is a runaway that bills for itself
        and still answers late."""
        state = scripted([
            _turn(calls=[{"id": "1", "name": "search_code", "arguments": '{"query": "x"}'}])
        ])

        events = await _collect(AskService(None), _messages(), _bundle())

        assert len(state["tool_calls"]) <= ask_service._MAX_TOOL_CALLS
        # It still answers rather than leaving the reader with a half-finished search.
        assert any(e["type"] == "token" for e in events)
        assert state["final_stream"] == 1


class TestFallback:
    async def test_an_endpoint_without_tools_still_answers(self, scripted, monkeypatch) -> None:
        """Small local models refuse tool definitions outright. Answering from the
        evidence already in the prompt is why it is pre-loaded."""
        state = scripted([_turn(deltas=["unused"])])

        async def refuses(messages, tools, spec=None, **kwargs):
            raise ToolsUnsupported("this model does not support tools")
            yield  # pragma: no cover - makes it a generator

        monkeypatch.setattr(ask_service, "stream_tool_completion", refuses)

        events = await _collect(AskService(None), _messages(), _bundle())

        assert [e["text"] for e in events if e["type"] == "token"] == ["fallback answer"]
        assert state["final_stream"] == 1
