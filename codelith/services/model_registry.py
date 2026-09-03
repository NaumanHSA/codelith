"""
The models this installation knows about, and which one serves each tier.

Three providers, and they do not take the same fields — the provider is chosen first
and only its own fields are then asked for. That is the same split `llm/providers.py`
enforces, for the same reason: they used to share one shape, and setting
`PROVIDER=openai` while a base URL still pointed at LM Studio meant the key was posted
to localhost, which **answered**, replying as whatever model it had loaded. A wrong
endpoint that returns 200 is worse than one that refuses.

  * `openai`    — a key and a model name. Endpoint fixed.
  * `anthropic` — a key and a model name. Endpoint fixed, and it is Anthropic's
    OpenAI-compatible layer, so the same client places the call.
  * `local`     — any OpenAI-compatible server: LM Studio, vLLM, Ollama, llama.cpp,
    a gateway. Needs a URL, a model name and a context window, because not one of
    the three can be assumed.

**Testing is not optional decoration.** An endpoint that cannot be reached should be
found out on a settings page, by somebody who is looking at it, rather than nine
minutes into an analysis. The test places a real call — a two-token completion, or one
embedding — because "the server is up" and "this model answers" are different facts and
only the second one matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.core.crypto import decrypt, encrypt
from codelith.core.exceptions import NotFoundError, ValidationError
from codelith.llm.providers import (
    ANTHROPIC_BASE_URL,
    EMBEDDING,
    LOCAL,
    LOCAL_BASE_URL,
    OPENAI,
    OPENAI_BASE_URL,
    OPENAI_CONTEXT_WINDOW,
    ModelSpec,
)
from codelith.models.model_config import ModelConfig, TierAssignment

logger = structlog.get_logger(__name__)

PROVIDERS = (OPENAI, "anthropic", LOCAL)
TIERS = ("quality", "fast", "embedding")

#: Where each hosted provider talks. Not settable — see the module docstring.
_FIXED_ENDPOINT = {OPENAI: OPENAI_BASE_URL, "anthropic": ANTHROPIC_BASE_URL}

#: A prompt short enough to cost nothing and specific enough that a wrong answer is
#: still a working endpoint. What is being tested is reachability, not comprehension.
_PROBE = "Reply with the single word: ok"


@dataclass(slots=True)
class TestResult:
    ok: bool
    detail: str
    #: Embedding tiers only — the width the model actually emits, measured rather
    #: than configured. See `knowledge/embedding_width.py` for why that matters.
    dimensions: int | None = None
    #: What the endpoint said it was, when it says. LM Studio ignores the model name
    #: in a request and answers as whatever it has loaded, so this is how a
    #: misconfigured local endpoint becomes visible instead of silently working.
    served_model: str | None = None

    def as_json(self) -> dict:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "dimensions": self.dimensions,
            "served_model": self.served_model,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }


class ModelRegistry:
    """CRUD over configured endpoints, plus the tier each one serves."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── reading ───────────────────────────────────────────────────────────────

    async def list(self) -> list[ModelConfig]:
        rows = await self.db.execute(select(ModelConfig).order_by(ModelConfig.label))
        return list(rows.scalars().all())

    async def get(self, config_id: int) -> ModelConfig:
        row = await self.db.get(ModelConfig, config_id)
        if row is None:
            raise NotFoundError("Model", config_id)
        return row

    async def assignments(self) -> dict[str, int]:
        """`{tier: model_config_id}` for the tiers that have been assigned."""
        rows = await self.db.execute(select(TierAssignment))
        return {a.tier: a.model_config_id for a in rows.scalars().all()}

    async def specs(self) -> dict[str, ModelSpec]:
        """
        The resolved endpoint for every assigned tier.

        Unassigned tiers are simply absent, and the caller falls back to `.env` —
        which is what makes this additive rather than a migration. An installation
        that has never opened the settings page behaves exactly as it did.
        """
        assigned = await self.assignments()
        if not assigned:
            return {}

        rows = await self.db.execute(
            select(ModelConfig).where(ModelConfig.id.in_(assigned.values()))
        )
        by_id = {c.id: c for c in rows.scalars().all()}
        return {
            tier: to_spec(by_id[config_id], tier)
            for tier, config_id in assigned.items()
            if config_id in by_id
        }

    # ── writing ───────────────────────────────────────────────────────────────

    async def create(self, **fields) -> ModelConfig:
        data = self._validated(fields)
        key = data.pop("api_key", "")
        row = ModelConfig(**data, api_key_encrypted=encrypt(key) if key else None)
        self.db.add(row)
        await self.db.flush()
        return row

    async def update(self, config_id: int, **fields) -> ModelConfig:
        row = await self.get(config_id)
        data = self._validated(fields, existing=row)
        key = data.pop("api_key", None)

        for column, value in data.items():
            setattr(row, column, value)
        # A blank key means "leave it alone", not "delete it". The API never returns
        # the stored key, so a form round-trip always posts an empty one, and
        # treating that as a deletion would wipe the credential on every rename.
        if key:
            row.api_key_encrypted = encrypt(key)
        await self.db.flush()
        return row

    async def delete(self, config_id: int) -> None:
        row = await self.get(config_id)
        holding = [t for t, cid in (await self.assignments()).items() if cid == config_id]
        if holding:
            raise ValidationError(
                f"'{row.label}' is serving the {', '.join(sorted(holding))} tier"
                f"{'s' if len(holding) > 1 else ''}. Point "
                f"{'those tiers' if len(holding) > 1 else 'that tier'} somewhere else first."
            )
        await self.db.delete(row)
        await self.db.flush()

    async def assign(self, tier: str, config_id: int) -> None:
        if tier not in TIERS:
            raise ValidationError(f"Unknown tier '{tier}'. Expected one of {', '.join(TIERS)}.")
        await self.get(config_id)  # 404s rather than storing a dangling id

        existing = await self.db.get(TierAssignment, tier)
        if existing is None:
            self.db.add(TierAssignment(tier=tier, model_config_id=config_id))
        else:
            existing.model_config_id = config_id
        await self.db.flush()

    # ── validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validated(fields: dict, existing: ModelConfig | None = None) -> dict:
        """
        What this provider needs, and nothing it does not.

        Fields belonging to another provider are dropped rather than stored. Keeping
        a base URL on an `openai` row would leave the shape that caused the original
        bug sitting in the database, waiting for a later reader to honour it.
        """
        provider = str(
            fields.get("provider") or (existing.provider if existing else "")
        ).strip().lower()
        if provider not in PROVIDERS:
            raise ValidationError(
                f"Unknown provider '{provider}'. Expected one of {', '.join(PROVIDERS)}."
            )

        label = str(fields.get("label") or (existing.label if existing else "")).strip()
        model = str(fields.get("model") or (existing.model if existing else "")).strip()
        if not label:
            raise ValidationError("Give this endpoint a name — it is how you pick it later.")
        if not model:
            raise ValidationError("A model name is required.")

        out: dict = {"label": label, "provider": provider, "model": model}
        if "api_key" in fields:
            out["api_key"] = str(fields.get("api_key") or "").strip()

        if provider == LOCAL:
            url = str(
                fields.get("base_url") or (existing.base_url if existing else "")
            ).strip()
            window = fields.get("context_window") or (
                existing.context_window if existing else None
            )
            if not url:
                raise ValidationError(
                    "A local endpoint needs a URL — LM Studio, vLLM, Ollama and a "
                    f"gateway are all different addresses. Default: {LOCAL_BASE_URL}"
                )
            # Embeddings are never trimmed, so nothing budgets against a window.
            if fields.get("tier_hint") != EMBEDDING and not window:
                raise ValidationError(
                    "A local endpoint needs a context window. Prompts are budgeted "
                    "against it, and without one there is no room to reserve for "
                    "evidence."
                )
            out["base_url"] = url
            out["context_window"] = int(window) if window else None
        else:
            # Hosted: the endpoint is fixed and the window is not something an
            # operator should have to look up.
            out["base_url"] = None
            out["context_window"] = None

        return out


def to_spec(config: ModelConfig, tier: str) -> ModelSpec:
    """One stored row, as something a call can be placed against."""
    if config.provider == LOCAL:
        return ModelSpec(
            tier=tier,
            provider=LOCAL,
            model=config.model,
            base_url=config.base_url or LOCAL_BASE_URL,
            api_key="not-needed",
            context_window=0 if tier == EMBEDDING else (config.context_window or 0),
        )
    return ModelSpec(
        tier=tier,
        provider=config.provider,
        model=config.model,
        base_url=_FIXED_ENDPOINT.get(config.provider, OPENAI_BASE_URL),
        api_key=decrypt(config.api_key_encrypted),
        context_window=0 if tier == EMBEDDING else OPENAI_CONTEXT_WINDOW,
    )


async def test_spec(spec: ModelSpec, *, embedding: bool) -> TestResult:
    """
    Place one real call and report what happened.

    Real, because "the server is listening" and "this model answers" are different
    facts and only the second is worth a green tick. Never raises: a failed test is
    the answer, not an error.
    """
    from openai import AsyncOpenAI

    if spec.provider in (OPENAI, "anthropic") and not spec.api_key.strip():
        return TestResult(ok=False, detail="No API key — this provider needs one.")

    client = AsyncOpenAI(api_key=spec.api_key or "not-needed", base_url=spec.base_url, timeout=30)
    try:
        if embedding:
            reply = await client.embeddings.create(model=spec.model, input="codelith probe")
            width = len(reply.data[0].embedding)
            return TestResult(
                ok=True,
                detail=f"Answered with a {width}-dimension vector.",
                dimensions=width,
                served_model=getattr(reply, "model", None),
            )

        reply = await client.chat.completions.create(
            model=spec.model,
            messages=[{"role": "user", "content": _PROBE}],
            max_completion_tokens=2000,
        )
        served = getattr(reply, "model", None)
        detail = "Answered."
        # LM Studio ignores the requested model name and replies as whatever it has
        # loaded. Saying so turns a silently wrong endpoint into a visible one.
        if served and spec.model not in served and served not in spec.model:
            detail = (
                f"Answered, but as '{served}' rather than '{spec.model}'. "
                "This endpoint serves whatever it has loaded, so the model name here "
                "is not what decides which model runs."
            )
        return TestResult(ok=True, detail=detail, served_model=served)
    except Exception as exc:
        return TestResult(ok=False, detail=_humanise(exc))
    finally:
        await client.close()


def _humanise(exc: Exception) -> str:
    """The failure as something to act on."""
    text = str(exc).lower()
    if "401" in text or "invalid_api_key" in text or "unauthorized" in text:
        return "The endpoint rejected the API key."
    if "404" in text or "model_not_found" in text or "does not exist" in text:
        return "That model name is not served by this endpoint."
    if "connection" in text or "connect" in text or "timed out" in text:
        return "Could not reach the endpoint — check the URL, and that the server is running."
    if "429" in text or "rate" in text:
        return "Rate limited. The endpoint is reachable; try again shortly."
    return str(exc)[:220]


__all__ = ["ModelRegistry", "PROVIDERS", "TIERS", "TestResult", "test_spec", "to_spec"]
