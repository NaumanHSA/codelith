# document-anything — Codebase Guide

## What This Is

AI Documentation Generation Platform. Ingests repos/files, runs a multi-agent LangGraph workflow, produces structured documentation in Markdown/PDF/DOCX/MkDocs/Docusaurus.

## Stack

- **API**: FastAPI + Python 3.12 (async throughout)
- **DB**: PostgreSQL via SQLAlchemy 2.0 async + Alembic migrations
- **Cache / Queue broker**: Redis
- **Vector search**: pgvector extension inside PostgreSQL — `code_chunks` table with HNSW index (no extra service)
- **Graph DB**: Neo4j (code entity relationships)
- **Task queue**: Celery (background ingestion + generation jobs)
- **Agent workflow**: LangGraph StateGraph
- **LLM**: `openai.AsyncOpenAI` pointed at LM Studio (`http://localhost:1234/v1`) — swap `LLM_BASE_URL` to use any OpenAI-compatible endpoint
- **Storage**: MinIO (S3-compatible) via boto3
- **Logging**: structlog (JSON in prod, colored in dev)
- **UI**: React 18 + Vite 6 + Tailwind 4 + shadcn/Radix, in `ui/` (same repo — there is no separate UI repository)

## Running Locally

```bash
cp .env.example .env       # fill in values
make dev                   # starts Docker infra + hot-reload API on :8000
make migrate               # apply DB migrations
make worker                # start Celery worker in another terminal

cd ui && npm install && npm run dev   # studio on :5173
```

## Key Conventions

- All DB access goes through `app/db/repositories/` — never query SQLAlchemy directly from routes or services
- Business logic lives in `app/services/` — routes are thin (validate input, call service, return schema)
- Every agent inherits from `app.agents.base.BaseAgent` and implements `async def run(state) -> state`
- LangGraph workflow state is a `TypedDict` defined in `app/workflows/states.py`
- All config is `pydantic-settings` in `app/config.py` — no hardcoded values anywhere
- LLM calls go through `app.llm.client.get_llm_client()` — never instantiate `openai.AsyncOpenAI` directly

## Project Layout

```
app/
  main.py          FastAPI app factory
  config.py        All settings (env-driven)
  api/v1/          Route handlers (thin)
  core/            Security, logging, exceptions, middleware
  db/              SQLAlchemy session + repositories
  models/          ORM models
  schemas/         Pydantic v2 request/response
  services/        Business logic
  agents/          11 specialized agents
  workflows/       LangGraph graphs + states
  ingestion/       Repo cloning + file parsers
  memory/          Short/long-term, pgvector, Neo4j
  llm/             LLM client + prompt templates
  tools/           Agent tools (file, git, search, diagram)
  formatters/      Markdown, DOCX, MkDocs, Docusaurus
  storage/         S3/MinIO client
  workers/         Celery app + task definitions
  observability/   OpenTelemetry + Prometheus

ui/                React studio (Vite) — see ui/README.md
```

## UI Conventions

- **Dark theme only** — no light mode, no toggle. `index.html` puts `class="dark"` on `<html>`.
  Style with the theme tokens in `ui/src/styles/theme.css` (`bg-background`, `text-brand`, …),
  never hardcoded Tailwind colors like `bg-white`
- API base URL comes from `VITE_API_URL` (set in `ui/.env.local`), defaulting to `:8000`
- All HTTP goes through `ui/src/app/lib/api.ts` — it attaches the JWT and refreshes on 401

## Testing

```bash
make test          # full suite
pytest tests/unit/ # unit only
pytest tests/integration/ # needs Docker infra running
```
