# Codelith

Open-source platform for understanding a codebase — and then doing things with that
understanding. Point it at a repository; it reads the code once, builds a knowledge
base, and everything after that is an app consuming it.

It runs entirely on your machine against [LM Studio](https://lmstudio.ai/) (or any
OpenAI-compatible endpoint). Nothing leaves your box.

---

## Read once, use many times

**Analysis is the product.** Clone the source, parse it, extract facts (routes,
entrypoints, dependencies, env vars, datastores), summarise every module, synthesise
the architecture, embed everything for retrieval, and persist it as a **knowledge
base** tied to the commit SHA.

That happens once per commit. Everything below is an app built on it, and none of
them re-read the repository.

| App | What it does | What it needs from the KB |
|---|---|---|
| **Documentation** | Structured documents in Markdown, DOCX, MkDocs or Docusaurus. Document types are offered from an evidence-backed menu, so a project with no HTTP routes is never offered an API Reference | retrieval, narratives |
| **Ask the code** | Grounded question answering. Every citation is checked against the evidence actually retrieved, and one that does not resolve is stripped | retrieval, code graph |

Analysing once is what makes the second and third thing you ask for cheap — and it is
why adding an app never means touching analysis.

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
git clone https://github.com/NaumanHSA/codelith.git
cd codelith
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

## Use it from your editor (MCP)

Codelith has already read your repository — chunked, embedded, with an import graph,
pinned to a commit. Coding agents re-derive that by grepping, from scratch, every
session. The MCP server lets them ask instead.

```jsonc
// .mcp.json — Claude Code, Cursor, and anything else speaking MCP
{
  "mcpServers": {
    "codelith": {
      "command": "python",
      "args": ["-m", "codelith.mcp"],
      "env": { "PYTHONPATH": "." }
    }
  }
}
```

Seven tools. `list_codebases` first — every other one takes a `codebase_id`, and the
ids are not guessable:

| Tool | Answers |
|---|---|
| `list_codebases` | What has been analysed, with commit and size |
| `search_code` | Semantic search over the source |
| `read_file` | A file as the knowledge base holds it |
| `find_callers` | Who calls a symbol — **no embedding encodes this** |
| `find_dependents` | Which files import a file |
| `blast_radius` | Everything that transitively reaches a file, with distance |
| `list_facts` | Routes, datastores, env vars, entrypoints and the rest |

Read-only, and local: nothing writes, and nothing is sent anywhere Codelith does not
already talk to.

---

## Architecture

### Layered Structure

```
API routes (codelith/api/v1/)
    ↓
Services (codelith/services/)
    ↓
Agents (codelith/agents/)   ←→   LangGraph Workflows (codelith/workflows/)
    ↓                            ↕
Repositories (codelith/db/repositories/)   Language providers (codelith/languages/)
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
human-review decision is made. Review is opt-in per job (`human_review: true`): when QA
does not pass every page the graph routes to `hold`, which stores the written pages on
the job and parks it as `awaiting_review`. Approving via
`POST /projects/{project_id}/compose/{job_id}/approve` replays only the tail —
`formatter` then `publisher` — against those stored pages, so approval publishes the
text that was reviewed rather than commissioning new text.

### Language support

Everything language-specific lives behind `LanguageProvider` in `codelith/languages/`.
Symbol extraction, manifest parsing, test/entrypoint detection and framework entity
detection are provider hooks; the knowledge base itself speaks a neutral vocabulary
(`codelith/knowledge/constants.py`) so a route is a route whether it came from a FastAPI
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
codelith/                       the importable package
├── main.py                     FastAPI app factory
├── config.py                   All settings (env-driven via pydantic-settings)
├── api/v1/                     Route handlers (thin) — mounts each app's router
├── core/                       Security, logging, exceptions, middleware
│   └── cancellation.py         Redis-backed CancellationToken + JobCancelled
├── db/ models/ schemas/        Persistence and contracts, shared by every app
├── services/                   Shared logic only — auth, audit, job, project,
│                               source, knowledge. An app's services live with it
├── knowledge/                  THE BASE: KB vocabulary, builder, retrieval,
│                               questions, artefacts, tools
├── languages/                  The multi-language seam
│   └── providers/              python · typescript · go · java
├── agents/analysis/            Analysis-phase agents
├── workflows/                  analysis_workflow + states
├── apps/                       ── THE APPS ─────────────────────────────
│   ├── registry.py             What exists, and what unlocks it
│   ├── ask/                    Answers, threads, routes
│   └── documentation/          Agents, workflows, services, tasks,
│                               formatters, routes
├── ingestion/ memory/ llm/     Cloning, stores, model client
├── storage/ workers/ tracing/  MinIO, Celery, per-job artifacts
└── observability/              OpenTelemetry + Prometheus

ui/                             React studio (Vite)
tests/                          unit/ + integration/
.dev/                           STATUS.md + the two records worth keeping
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
- [.dev/STATUS.md](.dev/STATUS.md) — where the work stands: what exists, what is weak, and
  what is open. The phase plans that built the product completed and were deleted; the git
  history is their record
- [.dev/QA_AGENT_PLAN.md](.dev/QA_AGENT_PLAN.md) — the Quality app, and what it
  deliberately does not do
- [.dev/ASK_SCORECARD.md](.dev/ASK_SCORECARD.md) — twenty questions hand-scored against a
  real repository
