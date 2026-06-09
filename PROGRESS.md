# document-anything — Work Log

## Phase 1 — Core API ✅
- FastAPI app factory, CORS, middleware, exception handlers
- PostgreSQL + SQLAlchemy 2.0 async; Alembic migrations
- Auth: JWT access/refresh tokens, bcrypt passwords, role-based (`admin`, `manager`, `reviewer`, `viewer`)
- Full CRUD: orgs, users, projects, sources, documents, jobs, agent logs, system settings
- MinIO/S3 storage client; Neo4j client; pgvector vector store
- Celery workers with queues: `ingestion`, `generation`, `export`
- OpenTelemetry + Prometheus observability

## Phase 2 — LangGraph Agent Pipeline ✅
- 12-agent LangGraph StateGraph: `coordinator → planner → repo_analyzer → code_understanding → architecture → strategy → writer(×N fan-out) → diagram → validator → reviewer → formatter → publisher`
- `BaseAgent` with `_call_llm`, `_call_llm_json` (JSON retry + repair), `_emit_log`, `_update_step`
- `ReActMixin` with `_run_react()` for self-directed tool-use agents
- Context window management: `count_tokens`, `trim_to_limit` (tiktoken)
- Tenacity retry with exponential backoff on all LLM calls
- Full tracing system (`app/tracing/`): `Tracer`, `RichTracer`, `NullSpanTracer`, `create_tracer`, `save_trace_artifacts`
- Per-job `JobSandbox` at `./runs/{job_id}/scratch|memory|outputs|trace`
- Embedding via LM Studio (`text-embedding-bge-m3`, 1024 dims, pgvector HNSW)
- Celery worker initialises structured logging via `worker_process_init` signal

## Phase 2 — API Fixes ✅
- `GET /api/v1/documents` — fixed broken nested route (was double-prefixed)
- `POST /api/v1/projects/{id}/jobs` — moved from jobs router to projects router (was 404)
- `GET /api/v1/projects/{id}/jobs` — added (was missing)
- `DELETE /api/v1/projects/{id}/sources/{src_id}` — added
- `GET /api/v1/jobs/{id}/stream` — SSE now accepts `?token=` query param for `EventSource` clients
- Schema fixes: `AgentLogOut` aliases (`agent`, `timestamp`, `extra`); `JobStepOut` aliases + `duration_seconds`; `JobOut` computed fields (`doc_types`, `output_formats`, `requires_human_review`)
- `ProjectOut` enriched with `stats` (source/job/doc counts) and `latest_job`
- Settings endpoint: `LlmConfig` and `TemplateItem` schemas aligned with UI contract

## Phase 2 — Logging / Tracing / Runs ✅
- SQL echo silenced: `session.py` now uses `SQLALCHEMY_ECHO` (default `false`); loggers suppressed at `ERROR` level
- Runs folder changed from `/tmp/jobs` (ephemeral) to `./runs` (persistent, project-local)
- `coordinator_agent` and `diagram_agent` now have tracer spans — all 12 agents fully traced
- `generation_tasks.py` logs `runs_dir` at both job start and completion

---

## Known Issues / Next Up

- **Ingestion pipeline** (`repo_analyzer`, `code_understanding`) not fully wired to sandbox scratch dir — repo still cloned to `REPO_SCRATCH_DIR` (/tmp/repos); needs to clone into `sandbox.scratch/repo/`
- **ReAct agents** (`architecture`, `writer`, `validator`) need MCP filesystem server installed: `npm install -g @modelcontextprotocol/server-filesystem`
- **Neo4j** code graph population not yet called from the workflow
- **PDF/DOCX/MkDocs/Docusaurus** formatters stubbed but not fully implemented
- **Phase 3**: Neo4j graph ingestion, richer code parsers
- **Phase 4**: PDF/MkDocs/Docusaurus output, OAuth2, full RBAC audit log
- **Phase 5**: OTEL exporter, Prometheus dashboards, K8s manifests, CI/CD

---

## Local Dev Setup

```bash
cp .env.example .env          # fill in values
make dev                      # Docker infra + hot-reload API on :8000
make migrate                  # apply DB migrations
make worker                   # Celery worker (separate terminal)

# LM Studio: load your LLM + text-embedding-bge-m3 (or any 1024-dim model)
# Update EMBEDDING_MODEL + VECTOR_DIMENSIONS in .env to match
conda run -n LLMs python scripts/test_embedding.py   # verify embedding endpoint
```
