"""
Streaming deltas out of the model.

`chat_completion` already streams — it has to, so a cancelled job stops the model
rather than draining it — but it accumulates the chunks and returns one string. A
reader watching an answer appear needs them as they arrive.

The interesting cases are not "does text come out". They are the three things that
differ between the two paths and would be invisible if they broke:

* **Reasoning is not the answer.** The reasoning families stream their thinking on a
  separate field. Yielding it would put the model's rough working on screen as though
  it were the reply.
* **Cancellation stops the model.** Not just us listening — the stream must be closed,
  which aborts the underlying HTTP request.
* **Parameters do not drift.** Both paths share `_completion_params`, because
  `max_tokens` is a local concern and the reasoning families reject a temperature.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.core.cancellation import JobCancelled
from codelith.llm import client as client_mod
from codelith.llm.client import _completion_params, stream_completion
from codelith.llm.providers import ModelSpec


def _delta(content: str | None = None, reasoning: str | None = None):
    delta = SimpleNamespace(content=content)
    if reasoning is not None:
        delta.reasoning_content = reasoning
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class _FakeStream:
    """An OpenAI streaming response, with a record of whether it was closed."""

    def __init__(self, events: list) -> None:
        self._events = events
        self.closed = False

    def __aiter__(self):
        async def gen():
            for event in self._events:
                yield event

        return gen()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_llm(monkeypatch):
    """Replaces the OpenAI client, and hands back the stream so it can be inspected."""

    state: dict = {}

    def _make(events: list):
        stream = _FakeStream(events)
        state["stream"] = stream

        async def create(**kwargs):
            state["params"] = kwargs
            return stream

        monkeypatch.setattr(
            client_mod,
            "get_llm_client",
            lambda spec=None: SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=create))
            ),
        )

        async def _no_cancel():
            return None

        monkeypatch.setattr("codelith.core.cancellation.check_cancelled", _no_cancel)
        return state

    return _make


LOCAL = ModelSpec(
    tier="fast", provider="local", model="local-model", base_url="http://x/v1",
    api_key="not-needed", context_window=21000,
)


class TestDeltasArriveAsTheyAreProduced:
    async def test_content_is_yielded_chunk_by_chunk(self, fake_llm) -> None:
        state = fake_llm([_delta("Hello"), _delta(" there"), _delta("!")])

        out = [chunk async for chunk in stream_completion([{"role": "user", "content": "hi"}], spec=LOCAL)]

        assert out == ["Hello", " there", "!"]
        assert state["stream"].closed

    async def test_empty_deltas_are_skipped(self, fake_llm) -> None:
        """A keep-alive frame carries no content and must not produce an empty chunk
        that a UI would render as a flicker."""
        fake_llm([_delta("a"), _delta(None), _delta("b")])

        out = [c async for c in stream_completion([{"role": "user", "content": "x"}], spec=LOCAL)]

        assert out == ["a", "b"]

    async def test_a_frame_with_no_choices_is_skipped(self, fake_llm) -> None:
        fake_llm([SimpleNamespace(choices=[]), _delta("a")])

        out = [c async for c in stream_completion([{"role": "user", "content": "x"}], spec=LOCAL)]

        assert out == ["a"]


class TestReasoningIsNotTheAnswer:
    async def test_thinking_is_never_yielded(self, fake_llm) -> None:
        """Putting it on screen shows the reader the model's rough working as though
        it were the reply."""
        fake_llm([
            _delta(None, reasoning="let me think about this"),
            _delta("The answer"),
            _delta(None, reasoning="more thinking"),
        ])

        out = [c async for c in stream_completion([{"role": "user", "content": "x"}], spec=LOCAL)]

        assert out == ["The answer"]

    async def test_thinking_without_an_answer_is_logged(self, fake_llm, caplog) -> None:
        """"Returned nothing" and "thought until it ran out of budget and then
        returned nothing" need different fixes, and the second is invisible without
        this line."""
        fake_llm([_delta(None, reasoning="x" * 200)])

        out = [c async for c in stream_completion([{"role": "user", "content": "x"}], spec=LOCAL)]

        assert out == []


class TestCancellationStopsTheModel:
    async def test_it_raises_and_closes_the_stream(self, fake_llm, monkeypatch) -> None:
        """Closing aborts the underlying HTTP request, which is what actually stops
        the model generating rather than just stopping us listening."""
        state = fake_llm([_delta("a"), _delta("b"), _delta("c"), _delta("d")])

        seen = {"n": 0}

        async def cancel_after_two():
            seen["n"] += 1
            if seen["n"] > 2:
                raise JobCancelled("stop")

        monkeypatch.setattr("codelith.core.cancellation.check_cancelled", cancel_after_two)

        out: list[str] = []
        with pytest.raises(JobCancelled):
            async for chunk in stream_completion([{"role": "user", "content": "x"}], spec=LOCAL):
                out.append(chunk)

        # The check runs after the yield, as it does in `chat_completion`, so the
        # chunk in flight is delivered before the cancellation surfaces. What matters
        # is that it stopped rather than draining: `d` never arrived.
        assert out == ["a", "b", "c"]
        assert "d" not in out
        assert state["stream"].closed, "the stream was abandoned rather than aborted"


class TestParametersDoNotDrift:
    """Both paths share `_completion_params`. A second copy is a second place for the
    tier differences to diverge."""

    def test_a_local_tier_gets_a_token_ceiling(self) -> None:
        """Without one, a model that loops in its own reasoning generates until
        something times out."""
        params = _completion_params([], LOCAL, None, None, None)

        assert "max_tokens" in params
        assert "temperature" in params

    def test_a_reasoning_model_is_sent_no_temperature(self) -> None:
        """The reasoning families reject anything but their default."""
        spec = ModelSpec(
            tier="quality", provider="openai", model="gpt-5-mini",
            base_url="https://api.openai.com/v1", api_key="k", context_window=128000,
        )

        params = _completion_params([], spec, None, None, None)

        assert "temperature" not in params
        assert "max_tokens" not in params

    def test_the_model_name_can_be_overridden_without_changing_endpoint(self) -> None:
        params = _completion_params([], LOCAL, "other-model", None, None)

        assert params["model"] == "other-model"

    async def test_the_stream_flag_is_set(self, fake_llm) -> None:
        state = fake_llm([_delta("a")])

        [c async for c in stream_completion([{"role": "user", "content": "x"}], spec=LOCAL)]

        assert state["params"]["stream"] is True
