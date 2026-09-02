from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from codelith.dependencies import AdminUser, CurrentUser, DbSession
from codelith.models.setting import SystemSetting

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
    What each tier is actually pointed at, resolved.

    **Read-only, and it says so.** Model configuration lives in `.env` and is read by
    `llm/providers.py` at call time; this endpoint used to persist an edited copy into
    the settings table that nothing ever read back, so the page offered fields that
    changed the display and not the behaviour. It reports the resolved specs now —
    the same values a job will use — and `editable` tells the studio to render them
    as facts rather than as inputs.

    Shaped around the choice that is actually made, *per tier*, and the two providers
    do not carry the same fields:

      * `openai` — a key and a model name. `base_url` and `context_window` come back
        as what the code will use, not as something to set.
      * `local` — any OpenAI-compatible server, where all three matter.

    `api_key` is never returned: this endpoint is admin-only, but a secret that is
    echoed back ends up in browser history, screenshots and bug reports.
    `openai_key_set` is the only thing the page needs.
    """

    quality_provider: str = "local"   # local | openai
    quality_model: str = "local-model"
    quality_base_url: str = ""
    quality_context_window: int = 21000

    fast_provider: str = "local"
    fast_model: str = "local-model"
    fast_base_url: str = ""
    fast_context_window: int = 21000

    embedding_provider: str = "local"
    embedding_model: str = ""
    embedding_base_url: str = ""

    openai_key_set: bool = False

    #: False while model settings come from `.env`. The studio renders the tiers
    #: read-only rather than offering inputs that would be silently discarded.
    editable: bool = False
    #: Anything `missing_configuration()` found — shown at the top of the page,
    #: because "openai with no key" should be visible before a job fails on it.
    problems: list[str] = Field(default_factory=list)

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
    from codelith.config import get_settings

    return Features(diagrams_enabled=get_settings().DIAGRAMS_ENABLED)


# ── LLM Config ────────────────────────────────────────────────────────────────

@router.get("/llm", response_model=LlmConfig)
async def get_llm_config(db: DbSession, _: AdminUser) -> LlmConfig:
    """
    The resolved endpoints, not a stored copy of them.

    Deliberately ignores anything previously persisted under `llm_config`. That row
    was written by the settings page and read by nothing, so serving it showed a
    configuration the application was not using — the worst possible answer for a page
    whose entire job is saying what is configured.
    """
    from codelith.config import get_settings
    from codelith.llm.providers import configured_specs, missing_configuration

    s = get_settings()
    specs = configured_specs()
    quality, fast, embedding = specs["quality"], specs["fast"], specs["embedding"]

    return LlmConfig(
        quality_provider=quality.provider,
        quality_model=quality.model,
        quality_base_url=quality.base_url,
        quality_context_window=quality.context_window,
        fast_provider=fast.provider,
        fast_model=fast.model,
        fast_base_url=fast.base_url,
        fast_context_window=fast.context_window,
        embedding_provider=embedding.provider,
        embedding_model=embedding.model,
        embedding_base_url=embedding.base_url,
        openai_key_set=bool(s.OPENAI_API_KEY.strip()),
        editable=False,
        problems=missing_configuration(),
        temperature=s.LLM_TEMPERATURE,
        max_tokens=s.LLM_MAX_TOKENS,
        max_react_iterations=s.REACT_MAX_ITERATIONS,
    )


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
