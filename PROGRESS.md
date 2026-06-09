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

## Phase 2 — Full Agent System ✅ DONE

> 12-agent LangGraph pipeline, pgvector semantic search, Send() fan-out for parallel writing.

- [x] All 12 agents implemented with full prompts
- [x] LangGraph StateGraph: coordinator→planner→repo_analyzer→code_understanding→architecture→strategy→[Send fan-out]→writer×N→diagram→validator→reviewer→[conditional]→formatter→publisher
- [x] `Annotated[list[dict], operator.add]` fan-out accumulator for parallel writers
- [x] pgvector replaces Qdrant — `code_chunks` table with HNSW index, cosine similarity
- [x] `app/tools/search_tools.py` — semantic_search via pgvector
- [x] Human-in-the-loop: conditional edge routes to END if `requires_human_review`

---

## Phase 2.5 — Hybrid Intelligence ✅ DONE

> ReAct inner loops for heavyweight agents, full execution tracing, per-job sandbox, MCP servers, retry/hallucination handling.

- [x] **Tracing** — `app/tracing/` (8 files, copied from opennarrate). `runtime.py` fixed imports. `_NoOpStepContext` fixed to support `outputs()`, `inputs()`, `set_error()`. All agents wrapped in `tracer(kind="agent", ...)`.
- [x] **Sandbox** — `app/core/sandbox.py`: `JobSandbox` creates `/tmp/jobs/{job_id}/{scratch,memory,outputs,trace}` per job.
- [x] **Context window management** — `app/llm/context_manager.py`: `count_tokens()` (tiktoken cl100k), `trim_to_limit()` (drops oldest pairs, keeps system msg), `compact_react_messages()`.
- [x] **BaseAgent upgrades** — `app/agents/base.py`: `_call_llm()` trims tokens + tenacity retry (3×, exp backoff). `_call_llm_json()` retries up to 3× with self-repair prompt appended.
- [x] **ReActMixin** — `app/agents/react_mixin.py`: `_mcp_session()` (filesystem), `_mcp_git_session()` (git), `_run_react()` (LangGraph `create_react_agent` with recursion-limit fallback), `_make_search_tool()` (pgvector), `_save_memory_checkpoint()` / `_load_memory_checkpoint()`.
- [x] **Architecture agent** — `app/agents/architecture.py`: ReAct first (MCP filesystem + git + pgvector), falls back to single-shot LLM.
- [x] **Writer agent** — `app/agents/writer.py`: ReAct first (MCP filesystem + pgvector), saves to `sandbox/outputs/{doc_type}.md` + `sandbox/memory/writer_{doc_type}.json`. Falls back to single-shot.
- [x] **Validator agent** — `app/agents/validator.py`: ReAct verifies all claims in one loop, falls back to per-claim single-shot.
- [x] **Planner, Strategy, Reviewer** — use `_call_llm_json()` with automatic JSON retry.
- [x] **LangChain wrapper** — `app/llm/langchain_client.py`: `get_langchain_llm()` for `create_react_agent`.
- [x] **generation_tasks.py** — initializes `JobSandbox` + `create_tracer()`, passes sandbox via `DocumentationWorkflow(sandbox=...)`, saves `trace.json` + `trace.md` to sandbox, stores paths in `job.config_json`.
- [x] **states.py** — added `sandbox: Any` field.
- [x] **documentation_workflow.py** — accepts `sandbox=` kwarg, injects into `initial_state`.
- [x] **job_service.py** — added `update_config()` for merging trace paths into config.
- [x] **Dependencies** — tiktoken, langchain-openai, langchain-mcp-adapters, mcp, rich, tenacity installed in LLMs conda env.
- [x] **MCP servers** — `@modelcontextprotocol/server-filesystem` + `@modelcontextprotocol/server-git` available via npx.

---

## Phase 3 — Memory & RAG ✅ DONE

- [x] `app/memory/vector_store.py` — pgvector cosine search (done in Phase 2)
- [x] `app/memory/graph_store.py` — Neo4j async client: File/Function/Class nodes, DEFINES/IMPORTS edges, `build_code_graph()`, `get_imports()`, `get_dependents()`, `get_module_overview()`, `get_symbols()`, `clear_project()`
- [x] `app/memory/long_term.py` — commit SHA–based job cache: skip re-embedding if the same git SHA was processed by a previous completed job
- [x] `app/agents/code_understanding.py` — now builds Neo4j graph after pgvector embedding; checks long-term cache before embedding; records commit SHA on completion
- [x] `app/agents/react_mixin.py` — added `_make_graph_tool()`: LangChain tool wrapping Neo4j queries (imports, dependents, symbols, module overview)
- [x] `app/agents/architecture.py` — uses graph tool + search tool in ReAct loop; receives `api_specs` + `infra_context` in user message
- [x] `app/ingestion/parsers/openapi_parser.py` — parses OpenAPI 3 / Swagger 2 YAML+JSON: title, version, base URL, all endpoints, schemas
- [x] `app/ingestion/parsers/infra_parser.py` — parses Dockerfile, docker-compose, k8s YAML → service topology with images, ports, env vars
- [x] `app/ingestion/repo/gitlab.py` — GitLab clone via gitpython (same interface as GitHub ingester)
- [x] `app/ingestion/repo/bitbucket.py` — Bitbucket clone via gitpython
- [x] `app/ingestion/pipeline.py` — runs all 4 parsers per source; exposes `_api_specs`, `_infra_context`, `_commit_sha`; supports local/github/gitlab/bitbucket
- [x] `app/agents/repo_analyzer.py` — passes `api_specs`, `infra_context` into workflow state
- [x] `app/workflows/states.py` — added `api_specs: list`, `infra_context: list` fields
- [x] RAG retrieval — `search_codebase` pgvector tool in all three ReAct agents (done in Phase 2.5)
- [ ] `app/ingestion/parsers/pdf_parser.py` — deferred to Phase 4 (output formats phase)

---

## Phase 4 — Output Formats & Enterprise ✅ DONE

- [x] `app/formatters/docx.py` — python-docx: headings → Word headings, code fences → monospace, bullets → List Bullet
- [x] `app/formatters/mkdocs.py` — ZIP export: mkdocs.yml (material theme + nav) + docs/*.md
- [x] `app/formatters/docusaurus.py` — ZIP export: docusaurus.config.js + sidebars.js + docs/*.mdx
- [x] `app/ingestion/parsers/pdf_parser.py` — pdfplumber text extraction (skips >50MB)
- [x] Full RBAC enforcement — `ManagerUser` / `ReviewerUser` / `CurrentUser` on all endpoints
- [x] Audit log — `app/models/audit.py` + `app/services/audit_service.py`; writes on all mutations in projects, jobs, documents, publisher agent
- [x] `app/api/v1/settings.py` — LLM config + doc-template CRUD (admin only)
- [x] `app/models/setting.py` — `SystemSetting` key-value JSONB store
- [x] `app/dependencies.py` — `_role_checker()` factory, `ManagerUser` / `ReviewerUser` type aliases
- [x] `app/agents/formatter.py` — enriches markdown (diagrams + frontmatter), generates DOCX/MkDocs/Docusaurus exports, uploads to S3
- [x] `app/agents/publisher.py` — creates `DocumentExport` DB records per S3 key, writes audit log
- [x] Alembic migration `d8ae677c6a7d_phase4_audit_settings` — adds `audit_logs`, `system_settings` tables (applied ✅)
- [ ] `app/formatters/pdf.py` — deferred (weasyprint needs libpango/libcairo system packages)
- [ ] OAuth2 Google + GitHub login — deferred (authlib not installed, needs OAuth app credentials)

---

## Phase 5 — Scale & Ops ✅ DONE

- [x] **Prometheus metrics** — `app/observability/metrics.py` enriched: `agent_duration`, `agent_runs_total`, `agent_errors_total`, `llm_calls_total`, `llm_call_duration`, `llm_tokens_total`, `celery_queue_depth`, `time_agent()` + `time_job()` context managers
- [x] **OpenTelemetry spans** — `app/observability/tracing.py`: `setup_tracing()` (dev=console, prod=OTLP), `agent_span()`, `workflow_span()` context managers. `OTEL_ENABLED` config flag added to `app/config.py`
- [x] **Metrics wired** — `documentation_workflow.py` wraps every `make_node()` with `time_agent()` + `agent_span()`; `generation_tasks.py` wraps workflow with `time_job()` + `workflow_span()` + records `job_total` on complete/fail; `base.py._call_llm()` records `llm_calls_total`, `llm_call_duration`, `llm_tokens_total` per call
- [x] **SSE streaming endpoint** — `GET /api/v1/jobs/{id}/stream` in `app/api/v1/jobs.py`: polls `AgentLogRepository.list_since()` every 1s, emits `data: <json>\n\n`, closes with `event: done` when job reaches terminal state
- [x] **Kubernetes manifests** — `k8s/`: `namespace.yaml`, `configmap.yaml`, `api-deployment.yaml`, `api-service.yaml`, `api-hpa.yaml` (HPA v2 on CPU+memory), `worker-deployment.yaml`, `worker-keda-scaledobject.yaml`, `ingress.yaml` (nginx, SSE-safe: proxy_buffering off)
- [x] **Helm chart** — `k8s/helm/`: `Chart.yaml`, `values.yaml`, templates for all resources (api + worker + ingress, HPA/KEDA toggleable via `values.yaml`)
- [x] **GitHub Actions CI** — `.github/workflows/ci.yml`: lint, unit tests, integration tests (postgres+redis services), docker build, push to GHCR on merge to main
- [x] **GitHub Actions doc-gen** — `.github/workflows/doc-gen.yml`: triggers on push to main (app/ changes) or manual dispatch; polls job status until completion
- [x] **GitLab CI** — `.gitlab-ci.yml`: lint, unit, integration, docker build+push, staging deploy, manual prod deploy
- [x] **Celery worker autoscaling** — KEDA `ScaledObject` in both raw manifest and Helm chart (toggleable, scales on Redis queue depth)
- [x] **Grafana dashboard** — `docker/grafana/dashboards/docany.json`: panels for job rate, job duration p50/p95/p99, LLM token rate, LLM success rate, agent duration by agent, agent error rate, stat tiles (total/completed/failed jobs), queue depth, LLM call duration. Provisioning wired into `docker-compose.yml`

---

## Notes

- **LLM:** Uses `openai.AsyncOpenAI` pointed at LM Studio for offline use. Change `LLM_BASE_URL` in `.env` to use any OpenAI-compatible cloud endpoint.
- **All LLM calls** go through `app.llm.client.chat_completion()` — never instantiate `AsyncOpenAI` directly.
- **All DB access** goes through `app/db/repositories/` — never query SQLAlchemy from routes or services directly.
- **New agents** must inherit `app.agents.base.BaseAgent` and implement `async def run(state) -> state`.
- **Vector search** uses pgvector inside PostgreSQL — `code_chunks` table, HNSW index on cosine distance. Qdrant was removed; `VectorStore` in `app/memory/vector_store.py` handles all embedding operations via SQLAlchemy.
- **`VECTOR_DIMENSIONS`** in `.env` must match the output size of your embedding model (default 1536 for most OpenAI-compatible models).
