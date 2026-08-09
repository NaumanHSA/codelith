from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.organizations import router as org_router
from app.api.v1.projects import router as project_router
from app.api.v1.jobs import router as job_router
from app.api.v1.documents import router as document_router
from app.api.v1.chat import router as chat_router
from app.api.v1.chat import threads_router as chat_threads_router
from app.api.v1.retrieval import router as retrieval_router
from app.api.v1.settings import router as settings_router

v1_router = APIRouter()

v1_router.include_router(auth_router)
v1_router.include_router(org_router)
v1_router.include_router(project_router)
v1_router.include_router(job_router)
v1_router.include_router(document_router)
v1_router.include_router(chat_router)
v1_router.include_router(chat_threads_router)
v1_router.include_router(settings_router)
# Development only — the route itself 404s in production.
v1_router.include_router(retrieval_router)
