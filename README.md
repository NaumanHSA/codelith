# Document Anything

Open-source documentation generation for codebases. Point it at a repository, it reads
the code and builds a knowledge base, then writes the documents you choose from it —
Markdown, DOCX, MkDocs or Docusaurus.

It runs entirely on your machine against [LM Studio](https://lmstudio.ai/) (or any
OpenAI-compatible endpoint). Nothing leaves your box.

---

## How it works

Documentation is generated in **two phases**, and the split is the point of the design.

**Phase 1 — Analyse (once per commit).** Clone the source, parse it, extract facts
(routes, entrypoints, dependencies, env vars, datastores), summarise every module,
synthesise the architecture, embed everything for retrieval, and persist it as a
**knowledge base** tied to the commit SHA.

**Phase 2 — Compose (as often as you like).** Pick document types from an
evidence-backed menu — the options are derived from what analysis actually found, so a
project with no HTTP routes is never offered an API Reference — and each section is
written by retrieving the relevant slice of the knowledge base.

Analysing once and composing many times is what makes the second and third document
cheap: composition never re-reads the repository.

```
  repository
      │
      │   PHASE 1 — ANALYSE  (once per commit)
      └─► clone → extract facts → embed → summarise modules
                → synthesise architecture → write narratives
                                │
                                ▼
                    ┌───────────────────────┐
                    │    KNOWLEDGE BASE     │   keyed by commit SHA
                    │  facts · summaries    │
                    │  narratives · chunks  │
                    └───────────┬───────────┘
                                │   "given this, what's worth writing?"
                                │
          PHASE 2 — COMPOSE  (per document request)
          plan → retrieve per section → write → diagram + QA
                → format → publish ──► documents
```

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Python 3.11+ (async) |
| UI | React 19 + Vite 8 + Tailwind 4 (light studio, Node ≥ 20.19) |
| Database | PostgreSQL + SQLAlchemy 2.0 async + Alembic |
| Cache / Queue broker | Redis |
| Task queue | Celery |
| Agent workflow | LangGraph |
| LLM | `openai` package → LM Studio (offline, OpenAI-compatible) |
| Vector search | pgvector (PostgreSQL extension — no extra service) |
| Graph DB | Neo4j (provisioned; graph ingestion not yet wired into the workflow) |
| Object storage | MinIO (S3-compatible) |
| Observability | Prometheus + Grafana + OpenTelemetry |
| Containerization | Docker + Docker Compose |

---

## Quick Start

### 1. Prerequisites

- Python 3.11 or newer
- Node.js 20.19+ (for the studio)
- Docker + Docker Compose
- [LM Studio](https://lmstudio.ai/) running locally with a model loaded and server started on `http://localhost:1234`

### 2. Clone & configure

```bash
git clone https://github.com/NaumanHSA/document-anything.git
cd document-anything
cp .env.example .env
```

Edit `.env` — the key settings:

```env
# Three models, each described by the same four settings. `openai` uses the API key;
# `local` needs no key at all — that is the only difference between them.
OPENAI_API_KEY=

MODEL_QUALITY_PROVIDER=local            # plan / write / review / architecture / diagram
MODEL_QUALITY=qwen/qwen3.5-9b
MODEL_QUALITY_BASE_URL=http://localhost:1234/v1
MODEL_QUALITY_CONTEXT_WINDOW=21000

MODEL_FAST_PROVIDER=local               # classify / extract / summarize
MODEL_FAST=liquid/lfm2.5-1.2b
MODEL_FAST_BASE_URL=http://localhost:1234/v1
MODEL_FAST_CONTEXT_WINDOW=21000

MODEL_EMBEDDING_PROVIDER=local
MODEL_EMBEDDING=text-embedding-nomic-embed-text-v1.5
MODEL_EMBEDDING_BASE_URL=http://localhost:1234/v1

VECTOR_DIMENSIONS=768                   # must match the embedding model's output size
```

To move a tier to OpenAI, change one word and the model name:

```env
MODEL_QUALITY_PROVIDER=openai
MODEL_QUALITY=gpt-5-mini
MODEL_QUALITY_BASE_URL=https://api.openai.com/v1
MODEL_QUALITY_CONTEXT_WINDOW=128000
```

The tiers are independent, which is the point: a 1.2b model can summarise 45 modules
locally while a hosted model writes the prose. **Embeddings never follow the quality
tier** — `VECTOR_DIMENSIONS` is written into `code_chunks.embedding` at migration time,
so moving the embedder means a migration that truncates that table and a full re-ingest.

The quality/fast split is a real speed lever, not decoration: module summarisation is
thousands of short calls and runs fine on a small model, while planning and writing
degrade badly on one. Point both tiers at the same model if you only have one loaded.

### 3. Install Python dependencies

```bash
pip install -e ".[dev]"
```

Or with uv (recommended):

```bash
uv sync
```

### 4. Start infrastructure

```bash
make dev
```

This starts: PostgreSQL (with pgvector), Redis, Neo4j, MinIO, Prometheus, Grafana — then launches the API on `http://localhost:8000`.

### 5. Run migrations & seed

```bash
make migrate          # creates all DB tables
make seed             # creates admin@docany.dev / admin1234
```

### 6. Start Celery worker (second terminal)

```bash
make worker
```

### 7. Start the UI (third terminal)

```bash
cd ui
pnpm install
pnpm dev              # studio on http://localhost:5173
```

Requires **Node 20.19 or newer**. The UI talks to `http://localhost:8000` by default;
copy `ui/.env.example` to `ui/.env.local` and set `VITE_API_URL` to point it elsewhere.

### 8. Explore the API

Open `http://localhost:8000/docs` for the interactive Swagger UI.

---

## Architecture

### Layered Structure

```
API routes (app/api/v1/)
    ↓
Services (app/services/)
    ↓
Agents (app/agents/)   ←→   LangGraph Workflows (app/workflows/)
    ↓                            ↕
Repositories (app/db/repositories/)   Language providers (app/languages/)
    ↓
PostgreSQL + pgvector / Neo4j / MinIO
```

### Analysis workflow (`analysis_workflow.py`)

Seven nodes, run once per commit. Produces a knowledge base, not a document.

```
repo_analyzer  →  structured_extractor  →  semantic_indexer  →  module_summarizer
     clone            routes, deps,           embed chunks         per-module
   + inventory        env vars, …             into pgvector         summaries
                                                                        ↓
                              kb_persister  ←  narrative_writer  ←  architecture_synthesizer
                              mark READY        how it works          layers, flows
```

### Composition workflow (`composition_workflow.py`)

Runs per document request, against the stored knowledge base.

```
kb_loader → strategy → planner → writer (retrieve-then-write, per section)
                                       ↓
                              diagram  ‖  qa      (parallel)
                                       ↓
                             gate → formatter → publisher → documents
```

`gate` is the join point for the parallel diagram/QA branches, and where the
human-review decision is made. **Known limitation:** when review is required the graph
routes to `END` with no checkpointer, so `POST /jobs/{id}/approve` cannot resume it —
tracked as E4 in [.dev/PLAN.md](.dev/PLAN.md).

### Language support

Everything language-specific lives behind `LanguageProvider` in `app/languages/`.
Symbol extraction, manifest parsing, test/entrypoint detection and framework entity
detection are provider hooks; the knowledge base itself speaks a neutral vocabulary
(`app/knowledge/constants.py`) so a route is a route whether it came from a FastAPI
decorator, an Express call or a Spring annotation.

**Python ships today** (stdlib `ast`). Adding a language means implementing one class
and registering it — no changes to the agents, workflows or schema.

### Cancellation

Cancelling actually stops work. `POST /jobs/{id}/cancel` sets a Redis-backed
`CancellationToken` (the signal has to cross the API→worker process boundary) and
revokes the Celery task. LLM calls stream by default so the token can be checked
between chunks and the HTTP request aborted mid-generation — without that, cancelling
just relabels a job that keeps generating.

### Project Layout

```
document-anything/
├── app/
│   ├── main.py                     FastAPI app factory
│   ├── config.py                   All settings (env-driven via pydantic-settings)
│   ├── dependencies.py             FastAPI DI (db session, current_user)
│   ├── api/v1/                     Route handlers (thin layer)
│   │   ├── auth.py                 /auth/register|login|refresh|me
│   │   ├── organizations.py        /organizations CRUD
│   │   ├── projects.py             /projects CRUD, sources, analyze, compose
│   │   ├── jobs.py                 /jobs status|logs|stream|approve|cancel
│   │   ├── documents.py            /documents list|get|publish|export
│   │   └── settings.py             /settings LLM config
│   ├── core/                       Security, logging, exceptions, middleware
│   │   └── cancellation.py         Redis-backed CancellationToken + JobCancelled
│   ├── db/                         SQLAlchemy session + repositories
│   ├── models/                     ORM models (User, Org, Project, Job, Document, KB)
│   ├── schemas/                    Pydantic v2 request/response schemas
│   ├── services/                   Business logic (auth, project, job, document,
│   │                               knowledge, source)
│   ├── knowledge/                  KB vocabulary, builder, retrieval, doc-type roles
│   ├── languages/                  Language abstraction — the multi-language seam
│   │   ├── taxonomy.py             Language-neutral symbol kinds
│   │   ├── base.py                 LanguageProvider ABC
│   │   ├── registry.py             Path → provider resolution
│   │   └── providers/python.py     Python provider (stdlib ast)
│   ├── agents/                     Agent classes (see below)
│   │   ├── analysis/               7 analysis-phase agents
│   │   └── composition/            4 composition-phase agents
│   ├── workflows/                  LangGraph StateGraphs + state TypedDicts
│   ├── ingestion/                  Repo cloners + file parsers
│   ├── llm/                        LLM client, model router, prompt templates
│   ├── memory/                     Short/long-term memory, vector + graph stores
│   ├── tools/                      Agent tools (file, git, search, diagram)
│   ├── tracing/                    Per-job trace artifacts under ./runs/{job_id}/
│   ├── formatters/                 Output format converters
│   ├── storage/                    S3/MinIO client
│   ├── workers/                    Celery app + task definitions
│   └── observability/              OpenTelemetry + Prometheus metrics
├── ui/                             React studio (Vite + Tailwind, light theme)
├── alembic/                        DB migrations
├── tests/
│   ├── unit/                       Unit tests (no DB required)
│   └── integration/                Integration tests (needs Docker infra)
├── scripts/
│   └── seed_dev.py                 Dev DB seeder
├── docker/
│   └── prometheus.yml              Prometheus scrape config
├── .dev/                           Architecture + UX plans and progress logs
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── Makefile
└── PROGRESS.md                     Build phase tracker
```

### Agents

| Phase | Agents |
|---|---|
| Analysis | `repo_analyzer`, `structured_extractor`, `semantic_indexer`, `module_summarizer`, `architecture_synthesizer`, `narrative_writer`, `kb_persister` |
| Composition | `kb_loader`, `strategy`, `planner`, `writer` — plus shared `diagram`, `qa`, `formatter`, `publisher` |
| Legacy single-shot | `coordinator`, `planner`, `repo_analyzer`, `code_understanding`, `architecture`, `strategy`, `writer` (kept for the pre-two-phase endpoint) |

Every agent inherits `app.agents.base.BaseAgent` and implements
`async def run(state) -> state`.

---

## API Overview

### Auth

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login → JWT tokens |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| GET | `/api/v1/auth/me` | Current user info |

### Projects and sources

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/projects` | List projects |
| POST | `/api/v1/projects` | Create project |
| POST | `/api/v1/projects/sources:probe` | Fetch and inspect a source **without creating anything** |
| POST | `/api/v1/projects/with-source` | Create project + first source atomically (422 leaves nothing behind) |
| GET | `/api/v1/projects/{id}` | Project detail with stats and latest job |
| PATCH | `/api/v1/projects/{id}` | Update project |
| DELETE | `/api/v1/projects/{id}` | Delete project |
| POST | `/api/v1/projects/{id}/sources` | Add a source to an existing project |
| DELETE | `/api/v1/projects/{id}/sources/{src_id}` | Remove a source |
| POST | `/api/v1/projects/{id}/upload` | Upload a zip or single file as a source |

### Two-phase generation

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/projects/{id}/analyze` | **Phase 1** — build the knowledge base (takes no doc type) |
| GET | `/api/v1/projects/{id}/knowledge-base` | What we know + evidence-backed doc-type suggestions (`null` if never analysed) |
| POST | `/api/v1/projects/{id}/compose` | **Phase 2** — write the chosen documents from the KB |
| POST | `/api/v1/projects/{id}/jobs` | Legacy single-shot: analyse and write in one job |
| GET | `/api/v1/projects/{id}/jobs` | List a project's jobs |

### Jobs and documents

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/jobs/{id}` | Poll job status and steps |
| GET | `/api/v1/jobs/{id}/logs` | Agent logs |
| GET | `/api/v1/jobs/{id}/stream` | SSE progress stream (`?token=` for `EventSource`) |
| POST | `/api/v1/jobs/{id}/approve` | Human review approval |
| POST | `/api/v1/jobs/{id}/cancel` | Cancel — revokes the task and aborts generation |
| GET | `/api/v1/documents` | List documents (`?project_id=` to scope) |
| GET | `/api/v1/documents/{id}` | Document content |
| PATCH | `/api/v1/documents/{id}` | Update document |
| POST | `/api/v1/documents/{id}/publish` | Publish a document |
| GET | `/api/v1/documents/{id}/export?format=` | Export (queued to a worker) |

---

## Supported Inputs

**Repositories:** GitHub, GitLab, Bitbucket, local folders, zip upload

**Code analysis:** Python today. Other languages are a provider implementation away —
see [Language support](#language-support). Files in other languages are still ingested
and indexed for retrieval; they just do not yet contribute extracted symbols.

**Documents:** PDF, DOCX, Markdown, OpenAPI/Swagger, Dockerfiles, Terraform, Kubernetes YAML

---

## Output Formats

Chosen per job via `output_formats`; the formatter agent writes each one to MinIO.

| Format | Generated by a job | Standalone `/documents/{id}/export` |
|---|---|---|
| Markdown | ✅ | ✅ |
| DOCX | ✅ | ❌ `NotImplementedError` |
| MkDocs site | ✅ | ❌ |
| Docusaurus site | ✅ | ❌ |
| PDF | ❌ no formatter exists | ❌ |

The export endpoint advertises more formats than it implements — it only wires
Markdown. Everything else has to come out of a generation job for now.

---

## Development

```bash
make lint         # ruff linter
make format       # ruff auto-format
make typecheck    # mypy
make test         # full pytest suite
```

---

## Docker Services

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 (minioadmin / minioadmin) |
| Neo4j Browser | http://localhost:7474 (neo4j / neo4jpassword) |
| Grafana | http://localhost:3000 (admin / admin) |
| Prometheus | http://localhost:9090 |

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Description |
|---|---|---|
| `MODEL_QUALITY_PROVIDER` | `local` | `local` or `openai` — serves plan / write / review / architecture / diagram |
| `MODEL_QUALITY` | `local-model` | Model name, exactly as the endpoint lists it |
| `MODEL_QUALITY_BASE_URL` | `http://localhost:1234/v1` | Where to connect |
| `MODEL_QUALITY_CONTEXT_WINDOW` | `21000` | What it will accept; ReAct compaction reads it |
| `MODEL_FAST_*` | — | The same four, for classify / extract / summarize |
| `MODEL_EMBEDDING_*` | — | Provider, model and base URL. Independent of the other tiers — see `VECTOR_DIMENSIONS` |
| `OPENAI_API_KEY` | — | Required only for tiers set to `openai` |
| `LLM_MAX_TOKENS` | `8192` | **Local only.** Hosted models are sent no ceiling |
| `LLM_STREAMING` | `true` | Stream completions — required for cancellation to interrupt generation |
| `DATABASE_URL` | postgres://... | PostgreSQL async connection string |
| `REDIS_URL` | redis://localhost:6379/0 | Redis connection (also carries cancellation flags) |
| `S3_ENDPOINT_URL` | http://localhost:9000 | MinIO endpoint |
| `VECTOR_DIMENSIONS` | `1536` | Must match your embedding model's output dimensions |
| `ANALYSIS_MAX_SUMMARISED_MODULES` | `40` | Cap on modules sent for summarisation |
| `ANALYSIS_SUMMARY_CONCURRENCY` | `6` | Parallel summary calls against the LLM |

---

## Build Phases

- [PROGRESS.md](PROGRESS.md) — build phase tracker
- [.dev/PLAN.md](.dev/PLAN.md) / [.dev/PROGRESS.md](.dev/PROGRESS.md) — the analyse/compose
  rearchitecture, including a decision log
- [.dev/UX_PLAN.md](.dev/UX_PLAN.md) / [.dev/UX_PROGRESS.md](.dev/UX_PROGRESS.md) — the
  studio UX overhaul
