# Build Progress Tracker

Tracks what is built, what is in progress, and what is planned across all phases.

---

## Phase 1 — Foundation (MVP Core) ✅ COMPLETE

> **Status:** Done and pushed. All 112 files, syntax-clean, committed to `main`.

### Infrastructure & Config
- [x] `pyproject.toml` — Python 3.12 project, all dependencies declared
- [x] `.env.example` — every env var documented with defaults
- [x] `.gitignore`
- [x] `Makefile` — `make dev`, `make migrate`, `make seed`, `make test`, `make worker`, `make lint`
- [x] `Dockerfile` — Python 3.12-slim + git + build tools
- [x] `docker-compose.yml` — 9 services: api, worker, postgres, redis, qdrant, neo4j, minio, minio-init, prometheus, grafana
- [x] `docker/prometheus.yml` — Prometheus scrape config
- [x] `CLAUDE.md` — codebase guide for AI-assisted development

### FastAPI Application Core
- [x] `app/main.py` — app factory, lifespan, router mounting, health endpoint
- [x] `app/config.py` — Pydantic BaseSettings, env-driven, all services configured
- [x] `app/dependencies.py` — `get_db`, `get_current_user`, `get_current_admin` DI
- [x] `app/core/logging.py` — structlog setup (JSON prod / colored dev)
- [x] `app/core/security.py` — JWT encode/decode, bcrypt password hashing
- [x] `app/core/exceptions.py` — AppException hierarchy + FastAPI handlers
- [x] `app/core/middleware.py` — CORS, request-id, timing middleware
- [x] `app/core/events.py` — lifespan startup/shutdown hooks

### Database Layer
- [x] `app/db/session.py` — async SQLAlchemy engine + session factory
- [x] `app/db/base.py` — DeclarativeBase + TimestampMixin
- [x] `alembic/env.py` + `alembic.ini` + `alembic/script.py.mako` — async Alembic setup

### ORM Models
- [x] `app/models/organization.py` — Organization, OrgMember
- [x] `app/models/user.py` — User, OAuthAccount
- [x] `app/models/project.py` — Project, ProjectSource
- [x] `app/models/job.py` — Job, JobStep, AgentLog
- [x] `app/models/document.py` — Document, DocumentExport

### Pydantic Schemas
- [x] `app/schemas/auth.py`
- [x] `app/schemas/organization.py`
- [x] `app/schemas/project.py`
- [x] `app/schemas/job.py`
- [x] `app/schemas/document.py`

### Repository Layer
- [x] `app/db/repositories/base.py` — Generic async CRUD BaseRepository
- [x] `app/db/repositories/user_repo.py`
- [x] `app/db/repositories/org_repo.py`
- [x] `app/db/repositories/project_repo.py`
- [x] `app/db/repositories/job_repo.py`
- [x] `app/db/repositories/document_repo.py`

### Service Layer
- [x] `app/services/auth_service.py` — register, login, refresh
- [x] `app/services/project_service.py` — CRUD + source management
- [x] `app/services/job_service.py` — create, start, complete, fail, approve, cancel, log
- [x] `app/services/document_service.py` — CRUD, publish, record exports

### API Routes (v1)
- [x] `app/api/v1/auth.py` — `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/me`
- [x] `app/api/v1/organizations.py` — `/organizations` CRUD
- [x] `app/api/v1/projects.py` — `/projects` CRUD + `/projects/{id}/sources`
- [x] `app/api/v1/jobs.py` — `/jobs` create, status, logs, approve, cancel
- [x] `app/api/v1/documents.py` — list, get, publish, export

### Celery Workers
- [x] `app/workers/celery_app.py` — Celery app, Redis broker, 3 queues
- [x] `app/workers/tasks/ingestion_tasks.py` — `run_ingestion_pipeline`
- [x] `app/workers/tasks/generation_tasks.py` — `run_documentation_workflow`
- [x] `app/workers/tasks/export_tasks.py` — `export_document_task`

### Ingestion Pipeline
- [x] `app/ingestion/repo/base.py` — BaseRepoIngester + CloneResult
- [x] `app/ingestion/repo/local.py` — local folder ingestion
- [x] `app/ingestion/repo/github.py` — GitHub/GitLab clone via GitPython (shallow)
- [x] `app/ingestion/parsers/code_parser.py` — symbol extraction (Python, JS, TS)
- [x] `app/ingestion/parsers/markdown_parser.py` — heading extraction
- [x] `app/ingestion/pipeline.py` — orchestrates all sources

### LLM Layer
- [x] `app/llm/client.py` — `openai.AsyncOpenAI` singleton → LM Studio (`base_url` configurable)
- [x] `app/llm/router.py` — model selection by task type (quality vs fast)
- [x] `app/llm/prompts/base.py` — PromptTemplate with `string.Template`
- [x] `app/llm/prompts/writer_prompts.py` — architecture, module, API doc prompts
- [x] `app/llm/prompts/planner_prompts.py` — documentation plan prompt
- [x] `app/llm/prompts/reviewer_prompts.py` — quality review prompt
- [x] `app/llm/prompts/validator_prompts.py` — fact-check prompt

### Agents
- [x] `app/agents/base.py` — BaseAgent: `run()`, `_call_llm()`, `_emit_log()`, `_update_step()`
- [x] `app/agents/coordinator.py` — reads job config, sets doc_types/output_formats
- [x] `app/agents/planner.py` — calls LLM to produce documentation plan JSON
- [x] `app/agents/repo_analyzer.py` — runs IngestionPipeline, exposes parsed codebase
- [x] `app/agents/writer.py` — generates markdown docs per doc_type via LLM
- [x] `app/agents/reviewer.py` — quality/style review via LLM
- [x] `app/agents/publisher.py` — saves documents to DB via DocumentService

### LangGraph Workflow
- [x] `app/workflows/states.py` — `DocumentationState` TypedDict
- [x] `app/workflows/documentation_workflow.py` — full StateGraph, conditional review gate

### Storage & Formatters
- [x] `app/storage/s3.py` — boto3 MinIO/S3 client (upload, download, presign, delete)
- [x] `app/formatters/markdown.py` — bytes renderer for Document → .md

### Observability
- [x] `app/observability/tracing.py` — OpenTelemetry OTLP setup
- [x] `app/observability/metrics.py` — Prometheus counters + `/metrics` endpoint

### Scripts & Tests
- [x] `scripts/seed_dev.py` — creates default org + admin user
- [x] `tests/conftest.py` — async test DB session + httpx AsyncClient fixture
- [x] `tests/integration/test_auth.py` — register, login, wrong password, /me
- [x] `tests/unit/ingestion/test_code_parser.py` — symbol extraction, ignore dirs, primary language
- [x] `tests/unit/services/test_auth_service.py` — duplicate email, wrong password

---

## Phase 2 — Full Agent System 🔲 TODO

> Build out all 12 agents and wire them into the LangGraph workflow properly.

- [ ] `app/agents/architecture.py` — service map + dependency graph agent
- [ ] `app/agents/code_understanding.py` — full AST parse → semantic graph (tree-sitter)
- [ ] `app/agents/strategy.py` — decides doc types, audiences, templates
- [ ] `app/agents/diagram.py` — Mermaid/PlantUML diagram generation
- [ ] `app/agents/validator.py` — fact-checks claims against source code
- [ ] `app/agents/formatter.py` — converts output to target format
- [ ] `app/tools/file_tools.py` — read_file, list_directory, search_in_file
- [ ] `app/tools/git_tools.py` — git_log, git_blame, diff_files
- [ ] `app/tools/search_tools.py` — semantic_search (Qdrant), graph_query (Neo4j)
- [ ] `app/tools/diagram_tools.py` — render_mermaid, validate_plantuml
- [ ] Update `documentation_workflow.py` — add architecture, code_understanding, strategy, diagram, validator, formatter nodes
- [ ] Human-in-the-loop: `POST /jobs/{id}/approve` fully integrated with workflow resume
- [ ] Parallel fan-out in LangGraph for multi-section WriterAgent runs
- [ ] `tests/unit/agents/` — unit tests per agent

---

## Phase 3 — Memory & RAG 🔲 TODO

- [ ] `app/memory/vector_store.py` — Qdrant: upsert, search, delete collections
- [ ] `app/memory/graph_store.py` — Neo4j: entity + relationship nodes for code graph
- [ ] `app/memory/short_term.py` — Redis-backed session memory
- [ ] `app/memory/long_term.py` — PostgreSQL-backed project knowledge store
- [ ] Embed code chunks on ingestion → Qdrant
- [ ] Build Neo4j knowledge graph from AST symbols
- [ ] RAG retrieval in WriterAgent (ground output with source context)
- [ ] `app/ingestion/parsers/pdf_parser.py` — pdfplumber
- [ ] `app/ingestion/parsers/docx_parser.py` — python-docx
- [ ] `app/ingestion/parsers/openapi_parser.py` — pyyaml + openapi-spec-validator
- [ ] `app/ingestion/parsers/infra_parser.py` — Dockerfile, Terraform, k8s YAML
- [ ] `app/ingestion/repo/gitlab.py` — GitLab clone
- [ ] `app/ingestion/repo/bitbucket.py` — Bitbucket clone
- [ ] Long-term memory: reuse parsed codebase across jobs in the same project

---

## Phase 4 — Output Formats & Enterprise 🔲 TODO

- [ ] `app/formatters/pdf.py` — weasyprint
- [ ] `app/formatters/docx.py` — python-docx
- [ ] `app/formatters/mkdocs.py` — mkdocs.yml + docs/ site structure
- [ ] `app/formatters/docusaurus.py` — docusaurus.config.js + MDX files
- [ ] OAuth2: Google + GitHub login (`/auth/oauth`)
- [ ] Full RBAC enforcement (admin/manager/reviewer/user) on all endpoints
- [ ] Audit log writes on all mutations
- [ ] `app/api/v1/settings.py` — model provider + template management endpoints
- [ ] Multi-tenancy hardening (org-scoped everything)
- [ ] Configurable LLM `base_url` per organization

---

## Phase 5 — Scale & Ops 🔲 TODO

- [ ] OpenTelemetry spans per agent node
- [ ] Prometheus metrics: token cost, job duration, success rate, agent errors
- [ ] Grafana dashboard provisioning (JSON)
- [ ] Kubernetes manifests / Helm chart (`k8s/`)
- [ ] GitHub Actions CI workflow (`.github/workflows/ci.yml`)
- [ ] GitHub Actions doc-generation workflow (trigger on push/PR)
- [ ] GitLab CI integration
- [ ] Celery worker autoscaling config
- [ ] Streaming job log endpoint (SSE or WebSocket)
- [ ] `make migrate-prod` deployment guide

---

## Notes

- **LLM:** Uses `openai.AsyncOpenAI` pointed at LM Studio for offline use. Change `LLM_BASE_URL` in `.env` to use any OpenAI-compatible cloud endpoint.
- **All LLM calls** go through `app.llm.client.chat_completion()` — never instantiate `AsyncOpenAI` directly.
- **All DB access** goes through `app/db/repositories/` — never query SQLAlchemy from routes or services directly.
- **New agents** must inherit `app.agents.base.BaseAgent` and implement `async def run(state) -> state`.
