"""
Which endpoint a tier actually talks to.

The application thinks in **tiers** — `quality` and `fast` — and `app/llm/router.py`
maps a task type onto one of them. This module is the only place that turns a tier
into a concrete endpoint: a provider, a base URL, a key, a model name and the context
length that endpoint will accept.

The split exists because the tiers are chosen independently. Running the fast tier on
a 1.2b model locally while the quality tier writes through OpenAI is the setup this is
for, and it should be two lines of `.env`, not a code change.

Everything downstream takes a `ModelSpec` rather than a bare model string, because a
model name alone is not enough to place a call once more than one endpoint exists —
that was the assumption baked into the old single-client design.

Embeddings resolve here too, and deliberately have their own provider: the embedding
model's output size is written into `code_chunks.embedding` at migration time, so it
must not follow the quality tier when that moves to a hosted model.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings

LOCAL = "local"
OPENAI = "openai"

QUALITY = "quality"
FAST = "fast"


@dataclass(frozen=True)
class ModelSpec:
    """Everything needed to place one call, resolved from settings."""

    tier: str
    provider: str
    model: str
    base_url: str
    api_key: str
    context_window: int

    @property
    def is_local(self) -> bool:
        return self.provider == LOCAL

    @property
    def is_reasoning_model(self) -> bool:
        """
        OpenAI's reasoning families, which accept only their default `temperature`.

        Nothing sends them a token ceiling — hosted models are not given one at all —
        so the only thing this decides is whether a temperature travels with the
        request. Matching on the family prefix is how OpenAI itself distinguishes
        them, and it lives here rather than at the call site so there is one place to
        correct when the next family lands.

        Local endpoints are excluded regardless of model name: LM Studio serves
        reasoning models too — qwen3.5 is one — and accepts the ordinary parameters.
        """
        return self.provider == OPENAI and self.model.lower().startswith(
            ("o1", "o3", "o4", "gpt-5")
        )

    def __str__(self) -> str:  # what shows up in logs and traces
        return f"{self.provider}:{self.model}"


def _spec(tier: str, provider: str, model: str) -> ModelSpec:
    s = get_settings()
    if provider == OPENAI:
        return ModelSpec(
            tier=tier,
            provider=OPENAI,
            model=model,
            base_url=s.OPENAI_BASE_URL,
            api_key=s.OPENAI_API_KEY,
            context_window=s.OPENAI_CONTEXT_WINDOW,
        )
    return ModelSpec(
        tier=tier,
        provider=LOCAL,
        model=model,
        base_url=s.LLM_LOCAL_BASE_URL,
        # Local endpoints authenticate nothing, but the OpenAI SDK refuses an empty
        # string, so a placeholder is used rather than whatever key is configured for
        # the hosted provider — that key has no business being sent to localhost.
        api_key=s.LLM_LOCAL_API_KEY or "not-needed",
        context_window=s.LLM_LOCAL_CONTEXT_WINDOW,
    )


def spec_for_tier(tier: str) -> ModelSpec:
    """The endpoint a tier resolves to. Unknown tiers fall back to quality."""
    s = get_settings()
    if tier == FAST:
        provider = s.LLM_FAST_PROVIDER
        model = s.OPENAI_FAST_MODEL if provider == OPENAI else s.LLM_LOCAL_FAST_MODEL
        return _spec(FAST, provider, model)

    provider = s.LLM_QUALITY_PROVIDER
    model = s.OPENAI_QUALITY_MODEL if provider == OPENAI else s.LLM_LOCAL_QUALITY_MODEL
    return _spec(QUALITY, provider, model)


def embedding_spec() -> ModelSpec:
    """
    Where embeddings are computed.

    Its own provider on purpose — see the module docstring and `VECTOR_DIMENSIONS`.
    """
    s = get_settings()
    return _spec("embedding", s.EMBEDDING_PROVIDER, s.EMBEDDING_MODEL)


def configured_specs() -> dict[str, ModelSpec]:
    """Every resolved endpoint, for the settings page and for startup logging."""
    return {
        QUALITY: spec_for_tier(QUALITY),
        FAST: spec_for_tier(FAST),
        "embedding": embedding_spec(),
    }


def missing_configuration() -> list[str]:
    """
    Settings that are required by the chosen providers and are not set.

    Checked at startup so "you selected openai and gave no key" is a message rather
    than a 401 forty minutes into an analysis run.
    """
    problems: list[str] = []
    for name, spec in configured_specs().items():
        if spec.provider == OPENAI and not spec.api_key.strip():
            problems.append(f"{name} tier is set to openai but OPENAI_API_KEY is empty")
        if not spec.model.strip():
            problems.append(f"{name} tier has no model name configured")
        if spec.provider == LOCAL and not spec.base_url.strip():
            problems.append(f"{name} tier is set to local but LLM_LOCAL_BASE_URL is empty")
    return problems


__all__ = [
    "ModelSpec",
    "spec_for_tier",
    "embedding_spec",
    "configured_specs",
    "missing_configuration",
    "LOCAL",
    "OPENAI",
    "QUALITY",
    "FAST",
]
