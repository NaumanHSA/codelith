from fastapi import APIRouter

from codelith.api.v1.apps import router as apps_router
from codelith.api.v1.auth import router as auth_router
from codelith.api.v1.evidence import router as evidence_router
from codelith.api.v1.jobs import router as job_router
from codelith.api.v1.models_api import router as models_router
from codelith.api.v1.organizations import router as org_router
from codelith.api.v1.preflight import router as preflight_router
from codelith.api.v1.projects import router as project_router
from codelith.api.v1.retrieval import router as retrieval_router
from codelith.api.v1.settings import router as settings_router
from codelith.apps.ask import router as chat_router
from codelith.apps.ask import threads_router as chat_threads_router
from codelith.apps.documentation.api import router as document_router
from codelith.apps.drift import router as drift_router

v1_router = APIRouter()

v1_router.include_router(auth_router)
v1_router.include_router(org_router)
v1_router.include_router(project_router)
v1_router.include_router(job_router)
v1_router.include_router(document_router)
v1_router.include_router(chat_router)
v1_router.include_router(drift_router)
v1_router.include_router(preflight_router)
v1_router.include_router(evidence_router)
v1_router.include_router(apps_router)
v1_router.include_router(chat_threads_router)
v1_router.include_router(models_router)
v1_router.include_router(settings_router)
# Development only — the route itself 404s in production.
v1_router.include_router(retrieval_router)
