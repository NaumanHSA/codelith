# Codelith

**Your coding agent re-reads your repository from scratch every session, by grepping.
Codelith reads it once and serves it.**

```bash
pipx install codelith          # or: pip install -e .
codelith analyse .             # reads the repo, builds a knowledge base
codelith mcp                   # serves it to Claude Code, Cursor, anything MCP
```

Point an editor at it and the agent can ask *what calls this*, *what breaks if I change
it*, *where is auth handled* — and get an answer from a structured reading of your code,
pinned to a commit, instead of thirty tool calls spent rediscovering the same thing.

```jsonc
// .mcp.json
{ "mcpServers": { "codelith": { "command": "codelith", "args": ["mcp"] } } }
```

**Nothing to install and nothing leaves your machine.** The knowledge base is a SQLite
file under `~/.codelith`; the models run in [LM Studio](https://lmstudio.ai/) or any
OpenAI-compatible endpoint you point it at. No database to run, no queue, no cloud.

That same knowledge base is what the other apps read — documentation, grounded Q&A —
and it is why the second thing you ask for is cheap.

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
| **What changed** | The difference between two readings of the same repository — modules added or rewritten, routes that came and went, and which written pages now describe code that is no longer there | modules, entities, written pages |
| **Before you edit** | What a change to a file or a symbol would touch: importers, transitive reach, call sites, whether a test covers it, and the pages that describe it. Also the `before_edit` MCP tool | code graph, entities, written pages |

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
| Database | SQLite + SQLAlchemy 2.0 async + Alembic — one file, nothing to install |
| Background work | One thread, in process |
| Agent workflow | LangGraph |
| LLM | `openai` package → LM Studio (offline, OpenAI-compatible) |
| Vector search | Exact cosine in numpy, over embeddings stored as float32 |
| Artefact storage | A directory under `~/.codelith` |
| Observability | OpenTelemetry + Prometheus metrics (exposed; scrape them if you want) |
| Containers | None |

---

## Quick Start

### 1. Prerequisites

- Python 3.11 or newer
- Node.js 20.19+ — only for the studio; the CLI and the MCP server need none
- [LM Studio](https://lmstudio.ai/) running locally with a model loaded and server started on `http://localhost:1234`

No database, no broker, no containers. That is the whole list.

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
MODEL_EMBEDDING=text-embedding-nomic-embed-text-v1.5-embedding
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
tier** — every stored vector has the width of the model that produced it, so changing
the embedder means re-ingesting every project. No migration (the column is a blob), but
no way to mix old vectors with new ones either.

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

### 4. Start it

```bash
uvicorn codelith.main:app --reload      # API on http://localhost:8000
make seed                                # admin@docany.dev / admin1234
```

There is nothing to install first and no migrate step. The knowledge base is a SQLite
file under `~/.codelith`, created on first run; artefacts go in a folder beside it.

This used to be six containers — PostgreSQL with pgvector, Redis, Neo4j, MinIO,
Prometheus, Grafana — plus a Celery worker in its own terminal, and it is why nobody
tried this. They were replaced by a file, a folder, a set in memory and a background
thread, and then deleted.

### 5. Start the UI (second terminal)

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
      "command": "codelith",
      "args": ["mcp"]
    }
  }
}
```

Or, in Claude Code:

```bash
claude mcp add codelith -- codelith mcp
```

The server speaks JSON-RPC on stdin and stdout, which is what an editor launches. It
writes nothing to stdout but the protocol — a stray line of prose there is a parse
error on the client, which is why `codelith mcp` prints no banner.

Eight tools. `list_codebases` first — every other one takes a `codebase_id`, and the
ids are not guessable:

| Tool | Answers |
|---|---|
| `list_codebases` | What has been analysed, with commit and size |
| **`before_edit`** | **What an edit would touch — call this first** |
| `search_code` | Semantic search over the source |
| `read_file` | A file as the knowledge base holds it |
| `find_callers` | Who calls a symbol — **no embedding encodes this** |
| `find_dependents` | Which files import a file |
| `blast_radius` | Everything that transitively reaches a file, with distance |
| `list_facts` | Routes, datastores, env vars, entrypoints and the rest |

`before_edit` is the one that changes what this is for. The others answer questions
about a codebase; that one is called *before* changing it. Give it a path or a symbol
and it comes back with what depends on it, whether anything tests it, and what has
already been written about it:

```
codelith/llm/client.py — high risk to edit — 3 file(s) import it directly,
11 reach it within 3 hops, nothing tests it, 2 written page(s) describe it.

Breaks first (nearest first):
  1 hop(s)  codelith/agents/base.py
  2 hops(s) codelith/workflows/analysis_workflow.py
  ...

No test file reaches this. A change here is unverified by the suite.

Written pages that describe it (they will need re-writing):
  reference/llm-client — The LLM client
```

No model call and four indexed queries, which is the point: a check an agent skips
under time pressure is a check that does not exist. The failure it prevents is not a
wrong edit but a confidently narrow one — correct in the file, and broken for four
callers nobody looked for.

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
SQLite — one file
```

### Analysis workflow (`analysis_workflow.py`)

Seven nodes, run once per commit. Produces a knowledge base, not a document.

```
repo_analyzer  →  structured_extractor  →  semantic_indexer  →  module_summarizer
     clone            routes, deps,           embed chunks         per-module
   + inventory        env vars, …             into the index        summaries
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

Cancelling actually stops work. `POST /jobs/{id}/cancel` sets an in-process
`CancellationToken` (the signal has to cross the API→worker process boundary) and
flag the workflow polls. LLM calls stream by default so the flag can be checked
between chunks and the HTTP request aborted mid-generation — without that, cancelling
just relabels a job that keeps generating.

### Project Layout

```
codelith/                       the importable package
├── main.py                     FastAPI app factory
├── config.py                   All settings (env-driven via pydantic-settings)
├── api/v1/                     Route handlers (thin) — mounts each app's router
├── core/                       Security, logging, exceptions, middleware
│   └── cancellation.py         CancellationToken + JobCancelled
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
├── storage/ workers/ tracing/  files, the inline worker, per-job artifacts
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

Chosen on export rather than before writing — the stored page is markdown, and every target is a transform of it.

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

## What is running

| | |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Studio | http://localhost:5173 |

One process for the first two, one for the studio, and one SQLite file under
`~/.codelith` holding all of it — the vectors, the code graph and the documents.
Backing Codelith up is copying that file.

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
| `LLM_MAX_TOKENS` | `12288` | **Local only.** Hosted models are sent no ceiling |
| `LLM_STREAMING` | `true` | Stream completions — required for cancellation to interrupt generation |
| `DATABASE_URL` | `sqlite+aiosqlite:///~/.codelith/codelith.db` | Rarely set. The default is a file under `CODELITH_HOME` |
| `VECTOR_DIMENSIONS` | `768` | Must match your embedding model's output dimensions |
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
