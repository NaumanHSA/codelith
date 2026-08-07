from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession, AdminUser
from app.models.setting import SystemSetting

router = APIRouter(prefix="/settings", tags=["Settings"])

# ── Schemas ────────────────────────────────────────────────────────────────────

class Features(BaseModel):
    """
    Which optional stages are switched on.

    Readable by any signed-in user, unlike the rest of this router: the studio needs
    it to render a pipeline honestly. A stage that is off shows as *queued* until it
    runs and reports itself disabled, which reads as "still to come" for the whole
    job — the one thing a progress view must never get wrong.
    """

    diagrams_enabled: bool = False

class LlmConfig(BaseModel):
    """
    What the two tiers are pointed at.

    Shaped around the choice that is actually made — *per tier, local or hosted* —
    rather than around one endpoint, which is what it assumed when both tiers had to
    share a base URL. The local fields are shared by whichever tiers are set to
    `local`; the OpenAI ones by whichever are set to `openai`.

    `api_key` is deliberately never returned: this endpoint is admin-only, but a
    secret that is echoed back ends up in browser history, screenshots and bug
    reports. `openai_key_set` says whether one is configured, which is the only thing
    the settings page needs to render.
    """

    quality_provider: str = "local"   # local | openai
    quality_model: str = "local-model"
    quality_base_url: str = "http://localhost:1234/v1"
    quality_context_window: int = 21000

    fast_provider: str = "local"
    fast_model: str = "local-model"
    fast_base_url: str = "http://localhost:1234/v1"
    fast_context_window: int = 21000

    embedding_provider: str = "local"
    embedding_model: str = ""
    embedding_base_url: str = "http://localhost:1234/v1"

    openai_key_set: bool = False

    temperature: float = 0.2
    max_tokens: int = 4096
    max_react_iterations: int = 20


class TemplateItem(BaseModel):
    doc_type: str
    name: str = ""
    system_prompt: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get(db, key: str) -> dict | None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def _set(db, key: str, value: dict, user_id: int) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
        row.updated_by_id = user_id
    else:
        db.add(SystemSetting(key=key, value=value, updated_by_id=user_id))
    await db.commit()


# ── Features ──────────────────────────────────────────────────────────────────

@router.get("/features", response_model=Features)
async def get_features(_: CurrentUser) -> Features:
    """What optional stages are enabled. Any signed-in user may read this."""
    from app.config import get_settings

    return Features(diagrams_enabled=get_settings().DIAGRAMS_ENABLED)


# ── LLM Config ────────────────────────────────────────────────────────────────

@router.get("/llm", response_model=LlmConfig)
async def get_llm_config(db: DbSession, _: AdminUser) -> LlmConfig:
    data = await _get(db, "llm_config")
    if data:
        return LlmConfig(**{k: v for k, v in data.items() if k in LlmConfig.model_fields})
    from app.config import get_settings
    s = get_settings()
    return LlmConfig(
        quality_provider=s.MODEL_QUALITY_PROVIDER,
        quality_model=s.MODEL_QUALITY,
        quality_base_url=s.MODEL_QUALITY_BASE_URL,
        quality_context_window=s.MODEL_QUALITY_CONTEXT_WINDOW,
        fast_provider=s.MODEL_FAST_PROVIDER,
        fast_model=s.MODEL_FAST,
        fast_base_url=s.MODEL_FAST_BASE_URL,
        fast_context_window=s.MODEL_FAST_CONTEXT_WINDOW,
        embedding_provider=s.MODEL_EMBEDDING_PROVIDER,
        embedding_model=s.MODEL_EMBEDDING,
        embedding_base_url=s.MODEL_EMBEDDING_BASE_URL,
        openai_key_set=bool(s.OPENAI_API_KEY.strip()),
        temperature=s.LLM_TEMPERATURE,
        max_tokens=s.LLM_MAX_TOKENS,
        max_react_iterations=s.REACT_MAX_ITERATIONS,
    )


@router.put("/llm", response_model=LlmConfig)
async def update_llm_config(req: LlmConfig, db: DbSession, user: AdminUser) -> LlmConfig:
    await _set(db, "llm_config", req.model_dump(), user.id)
    return req


# ── Doc Templates ─────────────────────────────────────────────────────────────

_DEFAULT_TEMPLATES = [
    TemplateItem(doc_type="architecture", name="Architecture", system_prompt="Document the system architecture including components, services, data flow, and deployment topology."),
    TemplateItem(doc_type="api", name="API Reference", system_prompt="Document all public API endpoints including authentication, request/response schemas, and error codes."),
    TemplateItem(doc_type="modules", name="Module Reference", system_prompt="Document each module's purpose, public API, usage examples, and dependencies."),
    TemplateItem(doc_type="getting_started", name="Getting Started", system_prompt="Write a beginner-friendly guide covering prerequisites, installation, and a quickstart example."),
    TemplateItem(doc_type="deployment", name="Deployment", system_prompt="Document deployment steps, environment variables, infrastructure requirements, and rollback procedures."),
    TemplateItem(doc_type="contributing", name="Contributing", system_prompt="Document contribution guidelines, code style, PR process, and development setup."),
    TemplateItem(doc_type="changelog", name="Changelog", system_prompt="Summarize changes by version with breaking changes highlighted."),
]

_DEFAULT_MAP = {t.doc_type: t for t in _DEFAULT_TEMPLATES}


@router.get("/templates", response_model=list[TemplateItem])
async def get_templates(db: DbSession, _: AdminUser) -> list[TemplateItem]:
    data = await _get(db, "doc_templates")
    if data and "templates" in data:
        stored = {t["doc_type"]: TemplateItem(**t) for t in data["templates"]}
        return [stored.get(t.doc_type, t) for t in _DEFAULT_TEMPLATES]
    return _DEFAULT_TEMPLATES


@router.put("/templates", response_model=TemplateItem)
async def upsert_template(req: TemplateItem, db: DbSession, user: AdminUser) -> TemplateItem:
    """Upsert a single template by doc_type into the stored list."""
    data = await _get(db, "doc_templates")
    templates: list[dict] = data.get("templates", []) if data else []

    updated = False
    for i, t in enumerate(templates):
        if t.get("doc_type") == req.doc_type:
            templates[i] = req.model_dump()
            updated = True
            break
    if not updated:
        templates.append(req.model_dump())

    await _set(db, "doc_templates", {"templates": templates}, user.id)
    return req


@router.get("/templates/{doc_type}", response_model=TemplateItem)
async def get_template(doc_type: str, db: DbSession, _: AdminUser) -> TemplateItem:
    data = await _get(db, "doc_templates")
    if data and "templates" in data:
        for t in data["templates"]:
            if t.get("doc_type") == doc_type:
                return TemplateItem(**t)
    if doc_type in _DEFAULT_MAP:
        return _DEFAULT_MAP[doc_type]
    raise HTTPException(status_code=404, detail=f"No template for doc_type '{doc_type}'")
