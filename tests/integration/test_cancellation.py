"""
Cancellation must actually stop work.

The bug these guard against: cancelling flipped a DB column, the UI said "cancelled",
and the worker kept streaming tokens out of LM Studio until the document was finished.
Every test here asserts on *work stopping*, not on status text.
"""

from __future__ import annotations

import asyncio

import pytest

from codelith.core.cancellation import (
    CancellationToken,
    JobCancelled,
    check_cancelled,
    clear_cancel,
    request_cancel,
    set_token,
)


@pytest.fixture(autouse=True)
async def _clean_token():
    set_token(None)
    yield
    set_token(None)


class TestToken:
    async def test_uncancelled_job_does_not_raise(self) -> None:
        job_id = 990_001
        await clear_cancel(job_id)
        async with CancellationToken(job_id) as token:
            assert await token.is_cancelled() is False
            await token.raise_if_cancelled()

    async def test_request_cancel_is_observed_by_a_separate_token(self) -> None:
        """
        The API and the worker are different processes, so the signal must survive
        crossing one — an in-process flag would never be seen.
        """
        job_id = 990_002
        await clear_cancel(job_id)
        async with CancellationToken(job_id, poll_interval=0) as token:
            assert await token.is_cancelled() is False
            await request_cancel(job_id)
            assert await token.is_cancelled() is True

            with pytest.raises(JobCancelled):
                await token.raise_if_cancelled()
        await clear_cancel(job_id)

    async def test_stale_flag_is_cleared_before_a_new_run(self) -> None:
        """A leftover flag would kill the next job with the same id at birth."""
        job_id = 990_003
        await request_cancel(job_id)
        await clear_cancel(job_id)
        async with CancellationToken(job_id, poll_interval=0) as token:
            assert await token.is_cancelled() is False

    async def test_check_cancelled_is_a_noop_without_a_token(self) -> None:
        set_token(None)
        await check_cancelled()  # must not raise outside a job

    async def test_ambient_token_is_reachable_from_agent_code(self) -> None:
        job_id = 990_004
        await clear_cancel(job_id)
        async with CancellationToken(job_id, poll_interval=0) as token:
            set_token(token)
            await check_cancelled()
            await request_cancel(job_id)
            with pytest.raises(JobCancelled):
                await check_cancelled()
        await clear_cancel(job_id)


class TestStreamingIsInterruptible:
    async def test_streamed_generation_aborts_partway(self, monkeypatch) -> None:
        """
        The whole reason completions stream: a non-streamed call is one opaque await,
        so there is no moment at which the request can be abandoned.
        """
        job_id = 990_010
        await clear_cancel(job_id)
        emitted: list[str] = []
        closed = {"value": False}

        class FakeDelta:
            def __init__(self, content): self.content = content

        class FakeChoice:
            def __init__(self, content): self.delta = FakeDelta(content)

        class FakeEvent:
            def __init__(self, content): self.choices = [FakeChoice(content)]

        class FakeStream:
            def __aiter__(self):
                async def gen():
                    for i in range(100):
                        emitted.append(f"tok{i}")
                        yield FakeEvent(f"tok{i} ")
                        await asyncio.sleep(0)
                return gen()

            async def close(self):
                closed["value"] = True

        class FakeCompletions:
            async def create(self, **kwargs):
                assert kwargs.get("stream") is True
                return FakeStream()

        class FakeClient:
            chat = type("Chat", (), {"completions": FakeCompletions()})()

        monkeypatch.setattr("codelith.llm.client.get_llm_client", lambda *a, **k: FakeClient())

        from codelith.llm.client import chat_completion

        async with CancellationToken(job_id, poll_interval=0) as token:
            set_token(token)
            await request_cancel(job_id)  # cancelled before the first chunk lands

            with pytest.raises(JobCancelled):
                await chat_completion([{"role": "user", "content": "hi"}], stream=True)

        # Stopped almost immediately rather than draining all 100 chunks...
        assert len(emitted) < 5
        # ...and the HTTP stream was closed, which is what stops the model generating.
        assert closed["value"] is True
        await clear_cancel(job_id)

    async def test_uncancelled_stream_returns_the_full_text(self, monkeypatch) -> None:
        class FakeDelta:
            def __init__(self, c): self.content = c

        class FakeChoice:
            def __init__(self, c): self.delta = FakeDelta(c)

        class FakeEvent:
            def __init__(self, c): self.choices = [FakeChoice(c)]

        class FakeStream:
            def __aiter__(self):
                async def gen():
                    for part in ("Hello", " ", "world"):
                        yield FakeEvent(part)
                return gen()

            async def close(self): ...

        class FakeCompletions:
            async def create(self, **kwargs): return FakeStream()

        class FakeClient:
            chat = type("Chat", (), {"completions": FakeCompletions()})()

        monkeypatch.setattr("codelith.llm.client.get_llm_client", lambda *a, **k: FakeClient())

        from codelith.llm.client import chat_completion

        set_token(None)
        out = await chat_completion([{"role": "user", "content": "x"}], stream=True)
        assert out == "Hello world"


class TestRetryDoesNotFightCancellation:
    async def test_cancellation_is_not_retried(self, monkeypatch) -> None:
        """
        `_chat_with_retry` retries on Exception. JobCancelled is an Exception, so a
        blanket predicate would retry it three times with exponential backoff — issuing
        more LLM calls after the user asked us to stop.
        """
        from codelith.agents.base import BaseAgent

        calls = {"n": 0}

        async def always_cancelled(messages, model=None, **kwargs):
            calls["n"] += 1
            raise JobCancelled(1)

        monkeypatch.setattr("codelith.agents.base.chat_completion", always_cancelled)

        class Probe(BaseAgent):
            name = "probe"

            async def run(self, state):  # pragma: no cover - unused
                return {}

        agent = Probe(db=None, job_id=1)
        with pytest.raises(JobCancelled):
            await agent._chat_with_retry([{"role": "user", "content": "x"}], "m")

        assert calls["n"] == 1, f"cancellation was retried {calls['n']} times"


class TestFanOutPropagation:
    async def test_cancellation_is_not_downgraded_to_a_section_failure(self) -> None:
        """
        The fan-out agents catch broad Exception and use gather(return_exceptions=True).
        Without explicit handling a cancellation looks like "that section failed" and the
        job carries on writing the rest.
        """
        import inspect

        from codelith.agents.analysis.module_summarizer import ModuleSummarizerAgent
        from codelith.agents.analysis.narrative_writer import NarrativeWriterAgent
        from codelith.apps.documentation.agents.writer import CompositionWriterAgent

        for agent in (CompositionWriterAgent, ModuleSummarizerAgent, NarrativeWriterAgent):
            src = inspect.getsource(agent)
            assert "except JobCancelled" in src or "isinstance(outcome, JobCancelled)" in src, (
                f"{agent.__name__} would swallow JobCancelled"
            )
