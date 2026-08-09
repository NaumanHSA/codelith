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

from app.llm.client import ToolsUnsupported
from app.services import ask_service
from app.services.ask_service import AskService
from app.knowledge.questions import Evidence, EvidenceBundle, QuestionPlan


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
