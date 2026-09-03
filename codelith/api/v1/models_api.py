"""
Configuring the models this installation talks to, from the application itself.

The settings page used to be a form that saved to a row nothing read back, because
model configuration lived in `.env` and was resolved at call time. That is the right
home for something one operator sets once on their own machine, and the wrong one for
an application people run — a user who wants to try a different writing model should
not be editing a file inside a container and restarting it.

**A library, and three assignments.** `POST /settings/models` adds an endpoint;
`PUT /settings/models/tiers` points a tier at one. Keeping those apart is what makes
switching cheap — three configured quality models and a dropdown, rather than editing
one set of fields in place and losing what was there.

**The key is never returned.** `api_key_set` says whether one is stored, which is all
a form needs to render. A secret echoed back to a browser ends up in history, in
screenshots, and in bug reports.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from codelith.dependencies import AdminUser, DbSession
from codelith.llm.providers import set_assigned
from codelith.services.model_registry import (
    TIERS,
    ModelRegistry,
    test_spec,
    to_spec,
)

router = APIRouter(prefix="/settings/models", tags=["Models"])

Provider = Literal["openai", "anthropic", "local"]
Tier = Literal["quality", "fast", "embedding"]


class ModelIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    provider: Provider
    model: str = Field(min_length=1, max_length=200)
    #: `local` only. Ignored for the hosted providers, whose endpoint is fixed —
    #: making it settable is how an API key once ended up posted to LM Studio.
    base_url: str | None = None
    context_window: int | None = None
    #: Write-only. Blank on an update means "leave the stored key alone", because the
    #: API never returns it and every form round-trip would otherwise wipe it.
    api_key: str | None = None
    #: `embedding` relaxes the context-window requirement — nothing budgets against a
    #: window for a request that is never trimmed.
    tier_hint: Tier | None = None


class ModelOut(BaseModel):
    id: int
    label: str
    provider: str
    model: str
    base_url: str | None
    context_window: int | None
    #: Whether a key is stored — never the key.
    api_key_set: bool
    last_test: dict = Field(default_factory=dict)
    #: The tiers currently pointed at this one.
    serving: list[str] = Field(default_factory=list)


class RegistryOut(BaseModel):
    models: list[ModelOut]
    #: `{tier: model_id}`. A tier missing from this is still resolved from `.env`.
    tiers: dict[str, int]
    #: Tiers with no assignment, so the page can say what is still falling back.
    unassigned: list[str]


class TestOut(BaseModel):
    ok: bool
    detail: str
    dimensions: int | None = None
    served_model: str | None = None


def _out(row, serving: list[str]) -> ModelOut:
    return ModelOut(
        id=row.id,
        label=row.label,
        provider=row.provider,
        model=row.model,
        base_url=row.base_url,
        context_window=row.context_window,
        api_key_set=bool(row.api_key_encrypted),
        last_test=row.last_test_json or {},
        serving=serving,
    )


async def _registry(db) -> RegistryOut:
    registry = ModelRegistry(db)
    rows = await registry.list()
    tiers = await registry.assignments()
    by_model: dict[int, list[str]] = {}
    for tier, model_id in tiers.items():
        by_model.setdefault(model_id, []).append(tier)
    return RegistryOut(
        models=[_out(r, sorted(by_model.get(r.id, []))) for r in rows],
        tiers=tiers,
        unassigned=sorted(t for t in TIERS if t not in tiers),
    )


async def _refresh(db) -> None:
    """
    Push the new assignments into the process that places the calls.

    `spec_for_tier` reads a module-level cache rather than the database, because it
    is called from synchronous code deep inside agents. Without this the change would
    not take effect until a restart, which is exactly the thing a settings page exists
    to avoid.
    """
    set_assigned(await ModelRegistry(db).specs())


@router.get("", response_model=RegistryOut)
async def list_models(db: DbSession, _: AdminUser) -> RegistryOut:
    return await _registry(db)


@router.post("", response_model=RegistryOut, status_code=201)
async def add_model(req: ModelIn, db: DbSession, _: AdminUser) -> RegistryOut:
    await ModelRegistry(db).create(**req.model_dump())
    await db.commit()
    return await _registry(db)


class TierIn(BaseModel):
    tier: Tier
    model_id: int


@router.put("/tiers", response_model=RegistryOut)
async def assign_tier(req: TierIn, db: DbSession, _: AdminUser) -> RegistryOut:
    await ModelRegistry(db).assign(req.tier, req.model_id)
    await db.commit()
    await _refresh(db)
    return await _registry(db)


@router.put("/{model_id}", response_model=RegistryOut)
async def update_model(model_id: int, req: ModelIn, db: DbSession, _: AdminUser) -> RegistryOut:
    await ModelRegistry(db).update(model_id, **req.model_dump())
    await db.commit()
    # An edit can change the endpoint a tier is already using.
    await _refresh(db)
    return await _registry(db)


@router.delete("/{model_id}", response_model=RegistryOut)
async def delete_model(model_id: int, db: DbSession, _: AdminUser) -> RegistryOut:
    await ModelRegistry(db).delete(model_id)
    await db.commit()
    return await _registry(db)


@router.post("/{model_id}/test", response_model=TestOut)
async def test_model(
    model_id: int, db: DbSession, _: AdminUser, tier: Tier = "quality"
) -> TestOut:
    """
    Place one real call against this endpoint and say what happened.

    Real, because "the server is listening" and "this model answers" are different
    facts and only the second is worth a green tick. The result is stored so the page
    can show it later without re-testing every endpoint on load.
    """
    registry = ModelRegistry(db)
    row = await registry.get(model_id)
    result = await test_spec(to_spec(row, tier), embedding=tier == "embedding")

    row.last_test_json = result.as_json()
    await db.commit()
    return TestOut(
        ok=result.ok,
        detail=result.detail,
        dimensions=result.dimensions,
        served_model=result.served_model,
    )


class UnsavedTestIn(ModelIn):
    """Testing a set of fields that has not been saved yet."""


@router.post("/test", response_model=TestOut)
async def test_unsaved(req: UnsavedTestIn, _: AdminUser) -> TestOut:
    """
    Test before saving.

    Worth its own route: the useful moment to find out an endpoint is unreachable is
    while the form is still open, not after storing something that does not work.
    """
    from codelith.models.model_config import ModelConfig

    tier = req.tier_hint or "quality"
    draft = ModelConfig(
        label=req.label,
        provider=req.provider,
        model=req.model,
        base_url=req.base_url,
        context_window=req.context_window,
        # Not persisted — this row is never added to the session.
        api_key_encrypted=None,
    )
    spec = to_spec(draft, tier)
    if req.api_key:
        # The key typed into the form, not a stored one — there is nothing stored yet.
        spec = replace(spec, api_key=req.api_key)

    result = await test_spec(spec, embedding=tier == "embedding")
    return TestOut(
        ok=result.ok,
        detail=result.detail,
        dimensions=result.dimensions,
        served_model=result.served_model,
    )
