"""
Which endpoint a tier actually talks to.

Three tiers — `quality`, `fast` and `embedding` — and each is described by the same
settings: a provider, a model name, a base URL and (for the two chat tiers) a context
window. `app/llm/router.py` maps a task type onto a tier; this module turns a tier
into something you can place a call against.

The provider decides exactly one thing: whether the request carries `OPENAI_API_KEY`
or a placeholder. Everything else is the same four values either way, which is what
makes moving a tier between local and hosted a one-word edit.

Downstream takes a `ModelSpec` rather than a bare model name, because a name alone is
not enough to place a call once the tiers can sit on different endpoints — that was
the assumption baked into the old single-client design.
"""

from __future__ import annotations

from dataclasses import dataclass

from codelith.config import get_settings

LOCAL = "local"
OPENAI = "openai"

QUALITY = "quality"
FAST = "fast"
EMBEDDING = "embedding"

#: Sent when a tier is `local`. Those endpoints authenticate nothing, but the OpenAI
#: SDK refuses an empty string — and a real key has no business reaching localhost.
_NO_KEY = "not-needed"

#: Where a provider talks when nothing says otherwise.
#:
#: This exists because "moving a tier is a one-word edit" has to be true. The base URL
#: used to default to LM Studio whatever the provider said, so setting only
#: `MODEL_QUALITY_PROVIDER=openai` sent the API key to `localhost:1234` — and LM Studio
#: **answered**, ignoring the model name and replying as whatever it had loaded. Every
#: quality call was served by the 1.2b fast model while the settings page said
#: `gpt-5.6-luna`, and nothing failed. A wrong endpoint that returns 200 is worse than
#: one that refuses, because there is nothing to notice.
_DEFAULT_BASE_URL = {
    LOCAL: "http://localhost:1234/v1",
    OPENAI: "https://api.openai.com/v1",
}

#: Hosts that cannot be a hosted provider, whatever the settings claim.
_LOOPBACK = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "host.docker.internal")


def _resolve_base_url(provider: str, configured: str) -> str:
    """An explicit setting always wins; otherwise the provider decides."""
    return configured.strip() or _DEFAULT_BASE_URL.get(provider, _DEFAULT_BASE_URL[LOCAL])


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

        Nothing sends a hosted model a token ceiling, so the only thing this decides
        is whether a temperature travels with the request. Matching on the family
        prefix is how OpenAI itself distinguishes them, and it lives here so there is
        one place to correct when the next family lands.

        Local endpoints are excluded whatever the model is called: LM Studio serves
        reasoning models too — qwen3.5 is one — and accepts the ordinary parameters.
        """
        return self.provider == OPENAI and self.model.lower().startswith(
            ("o1", "o3", "o4", "gpt-5")
        )

    def __str__(self) -> str:  # what shows up in logs and traces
        return f"{self.provider}:{self.model}"


def spec_for_tier(tier: str) -> ModelSpec:
    """The endpoint a tier resolves to. Unknown tiers fall back to quality."""
    s = get_settings()

    if tier == FAST:
        provider, model = s.MODEL_FAST_PROVIDER, s.MODEL_FAST
        base_url, window = s.MODEL_FAST_BASE_URL, s.MODEL_FAST_CONTEXT_WINDOW
    elif tier == EMBEDDING:
        provider, model = s.MODEL_EMBEDDING_PROVIDER, s.MODEL_EMBEDDING
        # Nothing trims an embedding request, so there is no window to resolve.
        base_url, window = s.MODEL_EMBEDDING_BASE_URL, 0
    else:
        tier = QUALITY
        provider, model = s.MODEL_QUALITY_PROVIDER, s.MODEL_QUALITY
        base_url, window = s.MODEL_QUALITY_BASE_URL, s.MODEL_QUALITY_CONTEXT_WINDOW

    return ModelSpec(
        tier=tier,
        provider=provider,
        model=model,
        base_url=_resolve_base_url(provider, base_url),
        api_key=s.OPENAI_API_KEY if provider == OPENAI else _NO_KEY,
        context_window=window,
    )


def embedding_spec() -> ModelSpec:
    """Where embeddings are computed — see the module docstring on why it is separate."""
    return spec_for_tier(EMBEDDING)


def configured_specs() -> dict[str, ModelSpec]:
    """Every resolved endpoint, for the settings page and for startup logging."""
    return {tier: spec_for_tier(tier) for tier in (QUALITY, FAST, EMBEDDING)}


def missing_configuration() -> list[str]:
    """
    Settings the chosen providers need and do not have.

    Checked at startup so "you selected openai and gave no key" is a message rather
    than a 401 forty minutes into an analysis run.

    The loopback check is here for a failure that never produced a 401 at all. A tier
    set to `openai` while its base URL points at LM Studio does not fail — LM Studio
    answers, ignores the model name, and replies as whatever it has loaded. The
    settings page said `gpt-5.6-luna` and a 1.2b model wrote every page. Nothing in a
    log or a trace showed it, because from the caller's side the call succeeded.
    """
    problems: list[str] = []
    for tier, spec in configured_specs().items():
        upper = tier.upper()
        if spec.provider == OPENAI and not spec.api_key.strip():
            problems.append(f"MODEL_{upper}_PROVIDER is openai but OPENAI_API_KEY is empty")
        if spec.provider == OPENAI and any(h in spec.base_url for h in _LOOPBACK):
            problems.append(
                f"MODEL_{upper}_PROVIDER is openai but MODEL_{upper}_BASE_URL points at "
                f"this machine ({spec.base_url}). A local server will answer and reply "
                f"as whatever model it has loaded, not as {spec.model}. Unset it to use "
                f"{_DEFAULT_BASE_URL[OPENAI]}."
            )
        if not spec.model.strip():
            problems.append(f"MODEL_{upper} is empty — no model name to call")
        if not spec.base_url.strip():
            problems.append(f"MODEL_{upper}_BASE_URL is empty — nowhere to connect")
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
    "EMBEDDING",
]
