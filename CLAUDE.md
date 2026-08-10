# Codelith — Codebase Guide

## What This Is

Open-source platform for **understanding a codebase and doing things with that
understanding**. Ingests repos/files, runs multi-agent LangGraph workflows to build a
knowledge base, then offers features that consume it.

**Analysis is the product; features are what it unlocks.** Read that sentence before
changing anything structural — the repository was originally built documentation-first
and named for it, and code written under the old premise couples the two. It should
not.

Two features exist today:

- **Documentation** — structured documents in Markdown/DOCX/MkDocs/Docusaurus
- **Ask the code** — grounded question answering with checked citations

**Three phases, and the split drives most of the design:**

1. **Analyse** (`app/workflows/analysis_workflow.py`) — build a knowledge base from the
   code, once per commit SHA. Takes no document type, and must never take one.
2. **Compose** (`app/workflows/composition_workflow.py`) — the documentation feature:
   write the requested documents from the stored KB, retrieve-then-write per section.
   Never re-reads the repository.
3. **Ask** (`app/services/ask_service.py`) — the second feature on the same KB, proving
   the pattern: it needed nothing from the doc pipeline.

A feature is defined by *what it needs from the knowledge base*. Adding one should mean
one entry in `app/features/registry.py` and one page — never a change to analysis. If
you find yourself editing an analysis agent to add a feature, stop; the feature is
asking for something the KB should hold for everyone.

`documentation_workflow.py` is the legacy single-shot pipeline, kept working for the
`POST /projects/{id}/jobs` endpoint. New work goes in the two-phase graphs.

## Stack

- **API**: FastAPI + Python 3.11+ (async throughout)
- **DB**: PostgreSQL via SQLAlchemy 2.0 async + Alembic migrations
- **Cache / Queue broker**: Redis
- **Vector search**: pgvector extension inside PostgreSQL — `code_chunks` table with HNSW index (no extra service)
- **Graph DB**: Neo4j (code entity relationships)
- **Task queue**: Celery (background ingestion + generation jobs)
- **Agent workflow**: LangGraph StateGraph
- **LLM**: `openai.AsyncOpenAI`. Three model tiers — quality, fast, embedding — each described by `MODEL_<TIER>_PROVIDER` (`local` | `openai`), `MODEL_<TIER>`, `MODEL_<TIER>_BASE_URL` and a context window, resolved by `app/llm/providers.py`. The provider decides only whether `OPENAI_API_KEY` is sent
- **Storage**: MinIO (S3-compatible) via boto3
- **Logging**: structlog (JSON in prod, colored in dev)
- **UI**: React 19 + Vite 8 + Tailwind 4, in `ui/` (same repo — there is no separate UI repository). **Needs Node ≥ 20.19**; the studio is a pnpm project

## Running Locally

```bash
cp .env.example .env       # fill in values
make dev                   # starts Docker infra + hot-reload API on :8000
make migrate               # apply DB migrations
make worker                # start Celery worker in another terminal

cd ui && pnpm install && pnpm dev      # studio on :5173 — needs Node >= 20.19
```

## Key Conventions

- All DB access goes through `app/db/repositories/` — never query SQLAlchemy directly from routes or services
- Business logic lives in `app/services/` — routes are thin (validate input, call service, return schema)
- Every agent inherits from `app.agents.base.BaseAgent` and implements `async def run(state) -> state`
- LangGraph workflow state is a `TypedDict` — `analysis_states.py`, `composition_states.py`, `states.py` (legacy)
- All config is `pydantic-settings` in `app/config.py` — no hardcoded values anywhere
- LLM calls go through `app.llm.client` — never instantiate `openai.AsyncOpenAI` directly.
  Resolve the endpoint with `app.llm.router.select_spec(task_type)` and pass the
  resulting `ModelSpec`; a bare model name is not enough to place a call now that the
  two tiers can sit on different providers
- **No language-specific code outside `app/languages/`.** Python's `ast`, file extensions,
  framework idioms — all of it lives behind `LanguageProvider`. Agents and the KB speak
  the neutral vocabulary in `app/languages/taxonomy.py` and `app/knowledge/constants.py`.
  Adding a language must mean adding one provider, not touching agents or schema
- Model tier is picked by task type in `app/llm/router.py` (`select_model`), not by the
  caller. `write`/`review`/`validate`/`architecture`/`plan` → quality; `classify`/
  `extract`/`diagram`/`summarize` → fast
- Long-running work must stay cancellable: never swallow `JobCancelled` in a broad
  `except Exception`, and never retry it. See `app/core/cancellation.py`
- A concurrent phase must not share one `AsyncSession` — fetch what you need before
  `asyncio.gather`, and avoid `return_exceptions=True` unless you log the exception

## Project Layout

```
app/
  main.py          FastAPI app factory
  config.py        All settings (env-driven)
  api/v1/          Route handlers (thin)
  core/            Security, logging, exceptions, middleware
    cancellation.py  Redis-backed CancellationToken + JobCancelled
  db/              SQLAlchemy session + repositories
  models/          ORM models
  schemas/         Pydantic v2 request/response
  services/        Business logic (incl. knowledge_service, source_service)
  knowledge/       KB vocabulary, builder, retrieval, doc-type roles
  languages/       Language abstraction — taxonomy, LanguageProvider, registry
    providers/       python.py (the only provider today)
  agents/
    analysis/        7 analysis agents (repo_analyzer → kb_persister)
    composition/     4 composition agents (kb_loader, strategy, planner, writer)
    *.py             Shared + legacy agents (diagram, qa, formatter, publisher, …)
  workflows/       analysis_workflow, composition_workflow, documentation_workflow (legacy)
  ingestion/       Repo cloning + file parsers
  memory/          Short/long-term, pgvector, Neo4j
  llm/             LLM client, model router, prompt templates
  tools/           Agent tools (file, git, search, diagram)
  tracing/         Per-job trace artifacts under ./runs/{job_id}/
  formatters/      Markdown, DOCX, MkDocs, Docusaurus
  storage/         S3/MinIO client
  workers/         Celery app + task definitions
  observability/   OpenTelemetry + Prometheus

ui/                React studio (Vite) — see ui/README.md
.dev/              Plans + progress logs (PLAN/PROGRESS, UX_PLAN/UX_PROGRESS)
```

## UI Conventions

The studio was rebuilt in August 2026 — light theme, orange accent, blueprint/terminal
character. The previous dark-only build is parked at `ui_backup/` and is not wired to
anything; delete it once nothing is being cross-referenced.

- **Light theme.** Tokens live in `ui/src/styles/theme.css` and are named for the design
  (`--paper`, `--ink`, `--hot`, `--rule`, `--sunk`, `--panel`), surfaced as Tailwind
  utilities (`bg-panel`, `text-ink-dim`, `border-rule`, `text-hot-ink`). Never hardcode a
  Tailwind colour like `bg-white` or `text-slate-600`. A dark variant is not built yet;
  the tokens are structured so it can be added without touching components
- Everything under `ui/src/app/` is the application. `lib/` holds the API client, types,
  formatters and the stage-narration table; `components/` and `pages/` the rest
- API base URL comes from `VITE_API_URL` (set in `ui/.env.local`), defaulting to `:8000`
- All HTTP goes through `ui/src/app/lib/api.ts` — it attaches the JWT, refreshes once on
  401, retries, and only then bounces to sign-in
- **IDs from the API are integers.** Type them as `number`
- Job progress: poll `GET /jobs/{id}`; the SSE stream carries logs only and times out
  after 10 minutes. Expected stages per job type live in `lib/narrate.ts` — `gate` is in
  the graph but never reports a step, so it is excluded from progress maths via
  `progressStages()`
- No external network at runtime: fonts are bundled in `src/assets/fonts`, and nothing
  may load from a CDN. The product's claim is that nothing leaves the machine

## Testing

```bash
make test          # full suite
pytest tests/unit/ # unit only
pytest tests/integration/ # needs Docker infra running
```
