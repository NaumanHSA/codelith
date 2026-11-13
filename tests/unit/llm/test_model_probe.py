"""
The connection test asks what a chat endpoint accepts, with real calls.

The plain test sent neither a temperature nor a tool, so gpt-6-luna passed it and then
failed every real answer: it rejects `temperature: 0.2`, and it refuses function tools
on chat completions. These pin that both are now asked, that a refusal is told apart
from an unrelated failure, and that reasoning is read from the reply.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.llm.providers import ModelSpec
from codelith.services import model_registry
from codelith.services.model_registry import test_spec as probe


class _Fake:
    """Stands in for `AsyncOpenAI`; refuses whichever parameters it is told to."""

    refuse: set[str] = set()
    flaky: bool = False
    reasoning_tokens: int | None = 0

    def __init__(self, **_: object) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw: object):
        if self.flaky and ("temperature" in kw or "tools" in kw):
            raise RuntimeError("Request timed out.")
        if "temperature" in kw and "temperature" in self.refuse:
            raise RuntimeError("Error code: 400 - Unsupported value: 'temperature' does not support 0.2")
        if "tools" in kw and "tools" in self.refuse:
            raise RuntimeError("Error code: 400 - function tools are not supported on this endpoint")
        details = SimpleNamespace(reasoning_tokens=self.reasoning_tokens)
        return SimpleNamespace(model=kw["model"], usage=SimpleNamespace(completion_tokens_details=details))

    async def close(self) -> None:
        return None


@pytest.fixture
def fake(monkeypatch):
    import openai

    _Fake.refuse = set()
    _Fake.flaky = False
    _Fake.reasoning_tokens = 0
    monkeypatch.setattr(openai, "AsyncOpenAI", _Fake)
    return _Fake


def _spec(model: str = "local-model", provider: str = "local") -> ModelSpec:
    return ModelSpec(
        tier="quality", provider=provider, model=model,
        base_url="http://localhost:1234/v1", api_key="k", context_window=8000,
    )


@pytest.mark.asyncio
async def test_an_endpoint_that_accepts_everything(fake) -> None:
    result = await probe(_spec(), embedding=False)
    assert result.ok
    assert result.capabilities == {"temperature": True, "tools": True, "reasoning": False}
    assert result.capability_detail is None


@pytest.mark.asyncio
async def test_the_gpt_6_luna_shape_is_caught(fake) -> None:
    fake.refuse = {"temperature", "tools"}
    fake.reasoning_tokens = 64
    result = await probe(_spec("gpt-6-luna", "openai"), embedding=False)
    assert result.ok  # it answers a plain message, which is why the old test passed
    assert result.capabilities == {"temperature": False, "tools": False, "reasoning": True}
    assert "temperature" in result.capability_detail["temperature"]
    assert "tools" in result.capability_detail["tools"]


@pytest.mark.asyncio
async def test_an_unrelated_failure_is_unknown_not_unsupported(fake) -> None:
    fake.flaky = True
    result = await probe(_spec(), embedding=False)
    assert result.capabilities["temperature"] is None
    assert result.capabilities["tools"] is None


def test_the_result_is_stored_with_its_capabilities() -> None:
    stored = model_registry.TestResult(ok=True, detail="Answered.", capabilities={"tools": False}).as_json()
    assert stored["capabilities"] == {"tools": False}
