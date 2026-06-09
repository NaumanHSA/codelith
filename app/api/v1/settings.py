from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import DbSession, AdminUser
from app.models.setting import SystemSetting

router = APIRouter(prefix="/settings", tags=["Settings"])

# ── Schemas ────────────────────────────────────────────────────────────────────

class LlmConfig(BaseModel):
    base_url: str = "http://localhost:1234/v1"
    model: str = "google/gemma-4-12b-qat"
    temperature: float = 0.2
    max_tokens: int = 4096


class TemplateItem(BaseModel):
    doc_type: str
    sections: list[str]
    tone: str = "technical"
    audience: str = "developers"


class TemplateList(BaseModel):
    templates: list[TemplateItem]


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


# ── LLM Config ────────────────────────────────────────────────────────────────

@router.get("/llm", response_model=LlmConfig)
async def get_llm_config(db: DbSession, _: AdminUser) -> LlmConfig:
    data = await _get(db, "llm_config")
    if data:
        return LlmConfig(**data)
    from app.config import get_settings
    s = get_settings()
    return LlmConfig(base_url=s.LLM_BASE_URL, model=s.LLM_QUALITY_MODEL,
                     temperature=s.LLM_TEMPERATURE, max_tokens=s.LLM_MAX_TOKENS)


@router.put("/llm", response_model=LlmConfig)
async def update_llm_config(req: LlmConfig, db: DbSession, user: AdminUser) -> LlmConfig:
    await _set(db, "llm_config", req.model_dump(), user.id)
    return req


# ── Doc Templates ─────────────────────────────────────────────────────────────

_DEFAULT_TEMPLATES = [
    TemplateItem(doc_type="architecture", sections=["Overview", "Services", "Data Flow", "Deployment"]),
    TemplateItem(doc_type="api", sections=["Authentication", "Endpoints", "Request/Response", "Errors"]),
    TemplateItem(doc_type="module", sections=["Purpose", "Public API", "Usage Examples", "Dependencies"]),
    TemplateItem(doc_type="tutorial", sections=["Prerequisites", "Installation", "Quickstart", "Next Steps"]),
    TemplateItem(doc_type="runbook", sections=["Prerequisites", "Steps", "Verification", "Rollback"]),
]


@router.get("/templates", response_model=TemplateList)
async def get_templates(db: DbSession, _: AdminUser) -> TemplateList:
    data = await _get(db, "doc_templates")
    if data and "templates" in data:
        return TemplateList(templates=[TemplateItem(**t) for t in data["templates"]])
    return TemplateList(templates=_DEFAULT_TEMPLATES)


@router.put("/templates", response_model=TemplateList)
async def update_templates(req: TemplateList, db: DbSession, user: AdminUser) -> TemplateList:
    await _set(db, "doc_templates", req.model_dump(), user.id)
    return req


@router.get("/templates/{doc_type}", response_model=TemplateItem)
async def get_template(doc_type: str, db: DbSession, _: AdminUser) -> TemplateItem:
    data = await _get(db, "doc_templates")
    if data and "templates" in data:
        for t in data["templates"]:
            if t["doc_type"] == doc_type:
                return TemplateItem(**t)
    for t in _DEFAULT_TEMPLATES:
        if t.doc_type == doc_type:
            return t
    raise HTTPException(status_code=404, detail=f"No template for doc_type '{doc_type}'")
