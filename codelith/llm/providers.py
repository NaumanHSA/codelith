"""
Which endpoint a tier actually talks to.

**Two providers, and they are not variations on each other.** The provider is decided
first and only that provider's settings are read afterwards, because the two need
genuinely different things and pretending otherwise is what broke this:

  * `openai` — a key and a model name. Nothing else. The endpoint is fixed, and the
    context window is not something a caller should have to look up.
  * `local` — any OpenAI-*compatible* server: LM Studio, vLLM, Ollama, llama.cpp,
    a gateway, another vendor's OpenAI-shaped API. These need a base URL, a model
    name and a context window, because none of the three can be assumed.

They used to share one shape — provider, model, base URL, window — with the provider
deciding only whether a real key travelled. That made `MODEL_QUALITY_PROVIDER=openai`
on its own resolve to LM Studio, which **answered**: it ignores the model name in a
request and replies as whatever it has loaded. The quality tier was served by a 1.2b
model while the settings page read `gpt-5.6-luna`, every call returned 200, and
nothing in a log or a trace showed it. A wrong endpoint that succeeds is worse than
one that refuses, so the shape that allowed it is gone.

Three tiers — `quality`, `fast`, `embedding` — each choosing its provider
independently. `codelith/llm/router.py` maps a task type onto a tier; this module
turns a tier into something you can place a call against.

Downstream takes a `ModelSpec` rather than a bare model name, because a name alone is
not enough to place a call once the tiers can sit on different endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass

from codelith.config import get_settings

LOCAL = "local"
OPENAI = "openai"

QUALITY = "quality"
FAST = "fast"
EMBEDDING = "embedding"

#: Sent when a tier is `local`. Those endpoints mostly authenticate nothing, but the
#: OpenAI SDK refuses an empty string — and a real key has no business being posted to
#: whatever happens to be listening on localhost.
_NO_KEY = "not-needed"

#: The `openai` provider's endpoint. Not a setting: a tier that says `openai` means
#: OpenAI, and everything else — including a proxy in front of OpenAI — is what the
#: `local` provider is for. Making this configurable is exactly how the key ended up
#: being posted to LM Studio.
OPENAI_BASE_URL = "https://api.openai.com/v1"

#: What the prompt budgeters assume a hosted model will take.
#:
#: `openai` deliberately has no context-window setting — it is not something a person
#: should have to look up to use their own account. But the budgeters need a number:
#: they decide how much retrieved evidence fits in a prompt, and zero would mean
#: "send none". Set generously, because the failure modes are asymmetric. Too high is
#: a context-length error the caller sees; too low silently drops evidence from every
#: answer and reads as the model being vague.
OPENAI_CONTEXT_WINDOW = 128_000

#: The default for a `local` tier that names no endpoint — LM Studio, which is what
#: the README tells people to install.
LOCAL_BASE_URL = "http://localhost:1234/v1"


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
    """
    The endpoint a tier resolves to. Unknown tiers fall back to quality.

    The provider is read first and dispatched on, and only then are that provider's
    settings looked at. A tier set to `openai` never reads a base URL or a window,
    so no combination of the two can point it anywhere but OpenAI.
    """
    s = get_settings()
    tier = tier if tier in (FAST, EMBEDDING) else QUALITY

    if tier == FAST:
        provider, model = s.MODEL_FAST_PROVIDER, s.MODEL_FAST
        base_url, window = s.MODEL_FAST_BASE_URL, s.MODEL_FAST_CONTEXT_WINDOW
    elif tier == EMBEDDING:
        provider, model = s.MODEL_EMBEDDING_PROVIDER, s.MODEL_EMBEDDING
        # Nothing trims an embedding request, so there is no window to resolve.
        base_url, window = s.MODEL_EMBEDDING_BASE_URL, 0
    else:
        provider, model = s.MODEL_QUALITY_PROVIDER, s.MODEL_QUALITY
        base_url, window = s.MODEL_QUALITY_BASE_URL, s.MODEL_QUALITY_CONTEXT_WINDOW

    if provider == OPENAI:
        return _openai_spec(tier, model, s.OPENAI_API_KEY)
    return _compatible_spec(tier, model, base_url, window)


def _openai_spec(tier: str, model: str, api_key: str) -> ModelSpec:
    """
    OpenAI: a key and a model name.

    No base URL and no window are read, because neither is a decision the operator
    should be making. Point somewhere else and you are using an OpenAI-compatible
    endpoint, which is `local` — that distinction is the whole reason these are two
    functions rather than one with branches.
    """
    return ModelSpec(
        tier=tier,
        provider=OPENAI,
        model=model,
        base_url=OPENAI_BASE_URL,
        api_key=api_key,
        # Embeddings are never trimmed, so the window is meaningless for that tier.
        context_window=0 if tier == EMBEDDING else OPENAI_CONTEXT_WINDOW,
    )


def _compatible_spec(tier: str, model: str, base_url: str, window: int) -> ModelSpec:
    """
    Any OpenAI-compatible server — LM Studio, vLLM, Ollama, llama.cpp, a gateway.

    All three values matter here and none can be assumed: the port differs per server,
    the model name is whatever that server calls it, and the window is whatever it was
    loaded with. An unset base URL falls back to LM Studio because that is what the
    README tells people to install; an unset window is a caller's problem, and
    `missing_configuration` says so rather than guessing one.
    """
    return ModelSpec(
        tier=tier,
        provider=LOCAL,
        model=model,
        base_url=base_url.strip() or LOCAL_BASE_URL,
        api_key=_NO_KEY,
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
    than a 401 forty minutes into an analysis run, after a repository has been cloned
    and embedded.

    Each provider is checked against what *it* needs, which is the point of splitting
    them. There is no longer a check for "openai pointed at localhost" because the
    shape no longer permits it: a tier set to `openai` never reads a base URL. That
    failure was silent — LM Studio answered as its own loaded model — and the fix for
    a silent failure is to make it unrepresentable rather than to detect it.
    """
    problems: list[str] = []
    for tier, spec in configured_specs().items():
        upper = tier.upper()

        if not spec.model.strip():
            problems.append(f"MODEL_{upper} is empty — no model name to call")

        if spec.provider == OPENAI:
            if not spec.api_key.strip():
                problems.append(
                    f"MODEL_{upper}_PROVIDER is openai but OPENAI_API_KEY is empty. "
                    f"Set the key, or set MODEL_{upper}_PROVIDER=local and give it a "
                    f"MODEL_{upper}_BASE_URL."
                )
            continue

        # `local` — an OpenAI-compatible server, where nothing can be assumed.
        if not spec.base_url.strip():
            problems.append(f"MODEL_{upper}_BASE_URL is empty — nowhere to connect")
        if tier != EMBEDDING and spec.context_window <= 0:
            problems.append(
                f"MODEL_{upper}_CONTEXT_WINDOW is {spec.context_window} — prompts are "
                f"budgeted against it, and a non-positive window leaves no room for "
                f"evidence."
            )
    return problems


__all__ = [
    "ModelSpec",
    "spec_for_tier",
    "embedding_spec",
    "configured_specs",
    "missing_configuration",
    "LOCAL",
    "OPENAI",
    "OPENAI_BASE_URL",
    "OPENAI_CONTEXT_WINDOW",
    "LOCAL_BASE_URL",
    "QUALITY",
    "FAST",
    "EMBEDDING",
]
