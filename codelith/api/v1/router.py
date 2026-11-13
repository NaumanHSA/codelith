from fastapi import APIRouter

from codelith.api.v1.agents import router as agents_router
from codelith.api.v1.apps import router as apps_router
from codelith.api.v1.atlas import router as atlas_router
from codelith.api.v1.auth import router as auth_router
from codelith.api.v1.codebase import router as codebase_router
from codelith.api.v1.evidence import router as evidence_router
from codelith.api.v1.findings import router as findings_router
from codelith.api.v1.flows import router as flows_router
from codelith.api.v1.guide import router as guide_router
from codelith.api.v1.health import router as health_router
from codelith.api.v1.jobs import router as job_router
from codelith.api.v1.models_api import router as models_router
from codelith.api.v1.organizations import router as org_router
from codelith.api.v1.preflight import router as preflight_router
from codelith.api.v1.projects import router as project_router
from codelith.api.v1.readings import router as readings_router
from codelith.api.v1.retrieval import router as retrieval_router
from codelith.api.v1.review import router as review_router
from codelith.api.v1.runbook import router as runbook_router
from codelith.api.v1.settings import router as settings_router
from codelith.apps.ask import router as chat_router
from codelith.apps.ask import threads_router as chat_threads_router
from codelith.apps.documentation.api import router as document_router
from codelith.apps.documentation.overview_api import router as documentation_overview_router
from codelith.apps.documentation.publish_api import router as publishing_router
from codelith.apps.drift import router as drift_router
from codelith.apps.qa import router as qa_router
from codelith.apps.tour import router as tour_router

v1_router = APIRouter()

v1_router.include_router(auth_router)
v1_router.include_router(org_router)
v1_router.include_router(project_router)
v1_router.include_router(job_router)
v1_router.include_router(document_router)
v1_router.include_router(documentation_overview_router)
v1_router.include_router(chat_router)
v1_router.include_router(drift_router)
v1_router.include_router(tour_router)
v1_router.include_router(qa_router)
v1_router.include_router(preflight_router)
v1_router.include_router(findings_router)
v1_router.include_router(atlas_router)
v1_router.include_router(review_router)
v1_router.include_router(flows_router)
v1_router.include_router(guide_router)
v1_router.include_router(health_router)
v1_router.include_router(runbook_router)
v1_router.include_router(readings_router)
v1_router.include_router(codebase_router)
v1_router.include_router(agents_router)
v1_router.include_router(evidence_router)
v1_router.include_router(apps_router)
v1_router.include_router(chat_threads_router)
v1_router.include_router(models_router)
v1_router.include_router(settings_router)
# Development only — the route itself 404s in production.
v1_router.include_router(retrieval_router)
v1_router.include_router(publishing_router)
