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

## Phase 3 — Analyse / Compose rearchitecture ✅

Split the single-shot pipeline into two phases so the document type is chosen *after* the
codebase is understood. Full tracker in [.dev/PLAN.md](.dev/PLAN.md) and
[.dev/PROGRESS.md](.dev/PROGRESS.md).

- **A** — Knowledge base data model (`kb`, `kb_modules`, `kb_entities`, `kb_narratives`),
  keyed by project + commit SHA; `app/db/repositories/knowledge/`
- **A0** — `app/languages/`: `LanguageProvider` + neutral taxonomy, so adding a language
  means adding one provider and touching neither agents nor schema
- **B** — `analysis_workflow.py`: 7 agents, `repo_analyzer → … → kb_persister`
- **C** — `composition_workflow.py`: retrieve-then-write per section; the per-section
  ReAct loop is gone
- **D** — `POST /projects/{id}/analyze`, `GET /{id}/knowledge-base`, `POST /{id}/compose`,
  plus the two-step UI flow
- **E1** — real model tiering (`LLM_FAST_MODEL`); module summaries 445s → 7.8s
- Result: analysis 571s → **172s**, and a second document type costs only its composition

## Phase 4 — Studio UX overhaul ✅

Tracker in [.dev/UX_PLAN.md](.dev/UX_PLAN.md) / [.dev/UX_PROGRESS.md](.dev/UX_PROGRESS.md).

- Design system: interaction tokens, `Row`/`ClickableCard`/`IconButton`/`Skeleton`
- **Real cancellation** — `app/core/cancellation.py`, streaming LLM calls, Celery revoke.
  Cancel used to only flip a DB column while the model kept generating
- Stage tree with narration derived from each step's output, not agent names
- Knowledge base card shows the evidence found; doc-type picker explains each option
- Project creation probes the source *before* creating anything
- Real Markdown rendering (tables, fenced code), single reading column, origin-aware back

---

## Known Issues / Next Up

- **PDF** — no formatter exists; `/documents/{id}/export` advertises it and raises
- **Standalone export** only implements Markdown; DOCX/MkDocs/Docusaurus work through a
  generation job's `output_formats` but not through the export endpoint
- **Neo4j** is populated but never queried — fold the useful edges into `kb_entities` or
  drop the service (Phase E3)
- **Human-review gate** returns `END` with no checkpointer, so approval cannot resume the
  graph; needs a LangGraph interrupt (Phase E4)
- **`diagram`** should be opt-in per doc type — 15% of run 18 (Phase E2)
- **Languages** — only Python has a provider; other files are indexed for retrieval but
  contribute no extracted symbols
- **Legacy pipeline** — `documentation_workflow.py` and the agents it owns
  (`coordinator`, `code_understanding`, `react_mixin`) exist only for the old
  `POST /projects/{id}/jobs` endpoint

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
