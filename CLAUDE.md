# Codelith — Codebase Guide

## What This Is

Open-source platform for **understanding a codebase and doing things with that
understanding**. Ingests repos/files, runs multi-agent LangGraph workflows to build a
knowledge base, then offers **apps** that consume it.

**Analysis is the product; apps are what it unlocks.** Read that sentence before
changing anything structural — the repository was originally built documentation-first
and named for it, and code written under the old premise couples the two. It should
not.

Five apps exist on `main` today:

- **Documentation** — structured documents in Markdown/DOCX/MkDocs/Docusaurus
- **Ask the code** — grounded question answering with checked citations
- **What changed** (`apps/drift/`) — the difference between two readings of the same
  repository, and which written pages now describe code that moved. It needs the
  codebase analysed at two commits; one reading is a photograph, two are a difference
- **Tour** (`apps/tour/`) — a guided walk on the knowledge graph for someone new to the
  code, assembled from the map, the flows and the narratives. No model call
- **QA** (`apps/qa/`) — what a QA engineer checks, run as a job against one reading's
  kept files: security, data leakage, error handling, things that will break,
  performance, configuration and deployment, test gaps. Every finding points at an
  exact line, says how sure it is (`confirmed`, `likely`, `suspected`), what it touches
  (from the risk ranking and the flows) and how to fix it; a fingerprint from the rule,
  file and code — not the line number — carries new/fixed and dismissals across runs

**QA was rebuilt from scratch in November 2026**, not restored from `feat/qa` (an
August snapshot of a narrower, linter-ranking Quality; leave that branch alone). Its
plan, phases Q1–Q6, is in the working notes. Where its pieces live: language rules in
each provider's `inspect()` (`_python_qa.py` on the syntax tree, `_pattern_qa.py` for
TypeScript, Go and Java), neutral checks in `apps/qa/checks/` (secrets, deploy, the
environment, untested entries), tables in `models/qa.py`. A secret is never copied into
a finding: its columns are stored and masked wherever code is shown. `codelith:
ignore` on a line silences what QA finds on it. Run tests (`apps/qa/sandbox.py`) installs and tests a
fresh copy in Docker — the install with the network, the tests and tools with none —
and the model designs tests that run there (`apps/qa/designed.py`). Mechanical fixes
are patches (`apps/qa/fixes.py`), checked against the tests when the sandbox ran; a
run exports as a Markdown fix plan or SARIF (`apps/qa/report.py`), and `codelith qa
--fail-on high` gates CI.

`codelith/mcp/` is **not** an app. It adds nothing of its own — it is a second
transport over the base, so other agents (Claude Code, Cursor) can query the knowledge
base directly. Nine of its tools come from `codelith/knowledge/tools.py` (among them
`qa_findings`, from `knowledge/findings.py`,
`trace_flow`, from `knowledge/flows.py`, and `how_to`, from `knowledge/guide.py`); `before_edit`
comes from `codelith/knowledge/preflight.py`, and `review_changes` from
`codelith/knowledge/review.py`.

`codelith/knowledge/findings.py` is base for the same reason: Ask, MCP (`qa_findings`),
the pre-flight, a review, AGENTS.md and the map all read what QA found, and none of
them may import the app. For each area it takes the latest finished run that checked
it, leaves out what people dismissed, and says which areas were never checked — so an
answer never calls an unchecked area clean. Ask's router adds QA evidence when a
question is about security, bugs, leaks, dependencies or tests, and the answer offers a
QA run (`suggest_qa`) for areas no run has checked.

`codelith/knowledge/review.py` is base for the same reason as the pre-flight below: MCP
serves it, and it derives nothing analysis should hold. It checks a change (collected
from git by `knowledge/changes.py`, wherever the working copy is) against the reading —
per-file reach, tests and pages from the pre-flight, facts added or removed, and the
codebase's shape from `knowledge/shape.py`. `shape.py` decides the knowledge graph's
columns too (the `/graph` response carries them), so the map and a review cannot
disagree about which way a link should run.

`codelith/knowledge/preflight.py` is also base rather than an app, for the same reason:
it derives nothing of its own. Given a path or a symbol it assembles what analysis
already stored — importers, transitive reach with distance, call sites, whether a test
reaches it, declared routes and env vars, and the written pages that cite it — into the
answer an agent wants *before* it edits. `reach_weight` lives there and is the ranking
every caller should sort on; it was Quality's, and it is in the base so that ranking by
reach does not require that app.

**Three phases, and the split drives most of the design:**

1. **Analyse** (`codelith/workflows/analysis_workflow.py`) — build a knowledge base from the
   code, once per commit SHA. Takes no document type, and must never take one. A new
   reading keeps what did not change from the previous one — vectors, module summaries,
   narratives, and while the structure is unchanged the architecture, site plan and
   questions — decided from file fingerprints in `codelith/knowledge/incremental.py`.
   A stage that adds model-written output must say when it may be kept
2. **Compose** (`codelith/apps/documentation/workflows/composition_workflow.py`) — the documentation app:
   write the requested documents from the stored KB, retrieve-then-write per section.
   Never re-reads the repository.
3. **Ask** (`codelith/apps/ask/service.py`) — the second app on the same KB, proving
   the pattern: it needed nothing from the doc pipeline. A question is gated by
   `codelith/knowledge/scope.py` before it is routed: retrieval always returns
   *something*, so without it "what is the capital of France" is answered from the
   three chunks least unlike a country.

An app is defined by *what it reads from the knowledge base* and, optionally, *what it
derives for itself*. Quality was the first with two stages — it parsed the checkout for
per-file symbol spans, because the KB stores symbols per module and records only where
they start — and the rule it established still holds: derived data stays inside the
app, so a project that never opens an app never pays for it.

An app is defined by *what it needs from the knowledge base*. Adding one should mean
one entry in `codelith/apps/registry.py` and one page — never a change to analysis. If
you find yourself editing an analysis agent to add an app, stop: the app is asking
for something the KB should hold for everyone.

**The rule is a test, not a convention.** `tests/unit/test_module_isolation.py` fails
if the base imports an app, or if one app imports another. Known exceptions live in
`KNOWN_LEAKS` with a reason, and that list can only shrink.

`documentation_workflow.py` (now under the documentation app) is the legacy single-shot pipeline, kept working for the
`POST /projects/{id}/jobs` endpoint. New work goes in the two-phase graphs.

## Stack

- **API**: FastAPI + Python 3.11+ (async throughout)
- **DB**: SQLite via SQLAlchemy 2.0 async + Alembic. One file under `~/.codelith`,
  created on first run. There is no separate migrate step and nothing to install
- **Vector search**: exact cosine in numpy over `code_chunks.embedding` (packed float32).
  The filters run in SQL; only the ranking runs in the process
- **Code graph**: six `graph_*` tables, walked with a recursive CTE
- **Background work**: one thread in this process, serial. `codelith/workers/inline.py`
- **Agent workflow**: LangGraph StateGraph
- **LLM**: `openai.AsyncOpenAI`. Three model tiers — quality, fast, embedding — each described by `MODEL_<TIER>_PROVIDER` (`local` | `openai`), `MODEL_<TIER>`, `MODEL_<TIER>_BASE_URL` and a context window, resolved by `codelith/llm/providers.py`. The provider decides only whether `OPENAI_API_KEY` is sent
- **Storage**: a directory under `~/.codelith`
- **Logging**: structlog (JSON in prod, colored in dev)
- **UI**: React 19 + Vite 8 + Tailwind 4, in `ui/` (same repo — there is no separate UI repository). **Needs Node ≥ 20.19**; the studio is a pnpm project

## Running Locally

```bash
make dev                             # API on :8000. Nothing to start first
cd ui && pnpm install && pnpm dev    # studio on :5173 — needs Node >= 20.19

make docker                          # or: one container, studio served on :8000
```

`make docker` is what the README leads with, and it is one service — `codelith` —
not the Postgres/Redis/Neo4j/MinIO stack this used to be. The model stays on the
host: compose maps `host.docker.internal`, and the studio says so at the field where
a model endpoint is typed. The app still serves `/metrics` in Prometheus format;
point your own scraper at it if you want one.

`.env` is optional — every setting has a working default and `.env.example` documents
them. The database is a file under `~/.codelith` (or `CODELITH_HOME`), created on first
run, so there is no migrate step for a fresh install.

**Reload is off by default on Windows**, and `dev.sh` says why: WatchFiles prints
"Reloading…", the replacement worker never starts, and the previous one keeps serving
while staying bound to the port. Set `RELOAD=1` to opt in — or restart by hand, which
is what the note recommends.

## Key Conventions

- All DB access goes through `codelith/db/repositories/` — never query SQLAlchemy directly from routes or services
- Business logic lives in `codelith/services/` — routes are thin (validate input, call service, return schema)
- Every agent inherits from `codelith.agents.base.BaseAgent` and implements `async def run(state) -> state`
- LangGraph workflow state is a `TypedDict` — `analysis_states.py`, `composition_states.py`, `states.py` (legacy)
- All config is `pydantic-settings` in `codelith/config.py` — no hardcoded values anywhere
- LLM calls go through `codelith.llm.client` — never instantiate `openai.AsyncOpenAI` directly.
  Resolve the endpoint with `codelith.llm.router.select_spec(task_type)` and pass the
  resulting `ModelSpec`; a bare model name is not enough to place a call now that the
  two tiers can sit on different providers
- **No language-specific code outside `codelith/languages/`.** Python's `ast`, file extensions,
  framework idioms — all of it lives behind `LanguageProvider`. Agents and the KB speak
  the neutral vocabulary in `codelith/languages/taxonomy.py` and `codelith/knowledge/constants.py`.
  Adding a language must mean adding one provider, not touching agents or schema
- Model tier is picked by task type in `codelith/llm/router.py` (`select_model`), not by the
  caller. `write`/`review`/`validate`/`architecture`/`plan` → quality; `classify`/
  `extract`/`diagram`/`summarize` → fast
- Long-running work must stay cancellable: never swallow `JobCancelled` in a broad
  `except Exception`, and never retry it. See `codelith/core/cancellation.py`
- A concurrent phase must not share one `AsyncSession` — fetch what you need before
  `asyncio.gather`, and avoid `return_exceptions=True` unless you log the exception

## Project Layout

```
codelith/                 the importable package (distribution name: codelith)
  main.py          FastAPI app factory
  config.py        All settings (env-driven)
  api/v1/          Route handlers (thin) — mounts each app's router
  core/            Security, logging, exceptions, middleware
    cancellation.py  CancellationToken + JobCancelled
    studio.py        Serves the built studio, mounted last so it shadows nothing
    runtime.py       Whether we are inside a container (the model form needs it)
  db/              SQLAlchemy session + repositories
    bootstrap.py     Schema on first run; migrations before create_all, never after
  models/          ORM models — ALL of them, including each app's. `source.py`:
                   every reading's files, each distinct content stored once
                   (`source_blobs` + `reading_files`); analysis writes them, a reading
                   from before is filled from git by `services/snapshot_service.py`
  schemas/         Pydantic v2 request/response
  services/        Shared business logic only (auth, audit, job, project, source,
                   knowledge). An app's services live with the app
  knowledge/       THE BASE — KB vocabulary, builder, retrieval, questions,
                   scope, artefacts, tools, preflight, doc-type roles
    lexical.py       Finds code by name — exact, restyled, misspelled, described.
                     The half an embedding cannot do; fused with vectors on rank
    scope.py         Whether a question is about this codebase at all — the answer
                     `questions.py` cannot give, since everything handed to it is
                     routed. Compares against what analysis found this repo to be,
                     reads the last turns, and fails open on every uncertain path
    services.py      Groups modules by the components analysis named for *this*
                     codebase, so the graph is not twelve fixed words everywhere
    atlas.py         The codebase as a map for the studio's atlas: every file with a
                     kind read from stored facts and roles (never from a language's
                     file names), its component, import edges, and fact nodes. Every
                     file has a part: what analysis named, else `services.place_files`
                     (Tests, Build & run, folder-mates, imports), with the reason
    detectors.py     What a file *is*, the same in every language — including the
                     project files a reading keeps (manifests, lockfiles, env files
                     with real values masked, Docker/CI/tooling, setup guides)
    runbook.py       How to run it: needs, install/run/test, the environment against
                     the templates. Read from the kept project files; providers answer
                     `run_info()` for their manifests
    compare.py       Two readings line by line, from the files each kept, with each
                     changed file's part, reach, tests and citing pages
    risk.py          Every file ranked by `reach_weight`; shares `risk_level` with
                     the pre-flight so the two cannot disagree
    incremental.py   What a new reading may keep from the last one, from file
                     fingerprints
    shape.py         The parts in columns (where work comes in → core → helpers →
                     data) and the links between them
    changes.py       A change from git: files, line ranges, new contents
    review.py        A change checked against the reading; kept in `change_reviews`
    flows.py         Every way in (route, command, job) followed through the recorded
                     calls to the data or service it reaches. Built per reading, cached
    guide.py         The agent instruction file (AGENTS.md / CLAUDE.md) and the
                     house-style recipes behind `how_to`. Assembled, never model-written
    churn.py         How often each file changed, read from git during analysis (the
                     checkout is gone after) and kept as `knowledge_bases.churn_json`
    hotspots.py      Changes × reach × no test; `timeline.py` each reading's size and
                     links against the columns
    findings.py      What QA found, for everyone but QA: open findings per area from
                     the latest run that checked it, and the areas never checked
    history.py       The commits analysis kept (`source_commits`; names, never emails),
                     the commits between two readings as git would list them, each
                     reading against the one before, and one file's own history
  languages/       Language abstraction — taxonomy, LanguageProvider, registry
    providers/       python, typescript, go, java
  agents/
    analysis/        analysis agents (repo_analyzer → kb_persister)
    *.py             base.py + the legacy single-shot agents
  workflows/       analysis_workflow + states (analysis only)
  apps/            ── THE APPS ──────────────────────────────────────────
    registry.py      App, AppState, APPS — what exists and what unlocks it
    ask/             service (answers), threads (persistence), api
    documentation/   agents, workflows, services, tasks, formatters, api
    drift/           service (two readings compared), api
    tour/            service (stops from the reading), api
    qa/              checks/ (code, secrets, deploy, environment, untested), service
                     (runs as jobs, fingerprints, states), impact, tasks, api
  mcp/             The KB over MCP — a second transport, not an app. Records each
                   tool call it answers (`agent_calls`) for the studio's Settings
  ingestion/       Repo cloning + file parsers
    scratch.py       Clones are working files: discarded when the job ends, and
                     swept at startup. Never touches a `local` source's own folder
  memory/          Vector store, the code graph in SQL
  llm/             LLM client, model router, prompt templates
  tools/           Agent tools (file, git, search, diagram)
  tracing/         Per-job trace artifacts under ./runs/{job_id}/
  storage/         Artefacts on disk
  workers/         The inline worker + analysis/ingestion tasks
  observability/   OpenTelemetry + Prometheus

ui/                React studio (Vite) — see ui/README.md
```

## UI Conventions

The studio was redesigned in November 2026 as a dark product app: a sidebar, pages
in a centred frame, real icons and brand logos, 3D only in the atlas. The light
blueprint theme from August is gone. `ui/README.md` has the map of the studio.
- **Layout:** every page sits in `.page-frame` (`index.css`): centred, at most 1440px
  wide, and the full height of the window. Width is capped on purpose; tool pages
  (assistant, atlas, live run) fill the height with their own scrolling panes. Below
  768px the sidebar becomes a slide-in panel
- **Dark only.** Tokens live in `ui/src/styles/theme.css` (`--paper`, `--ink`, `--hot`,
  `--rule`, `--sunk`, `--panel`, plus the newer `--hover`, `--line-2`, `--shadow`),
  surfaced as Tailwind utilities (`bg-panel`, `text-ink-dim`, `border-rule`,
  `text-hot-ink`). Never hardcode a Tailwind colour like `bg-white` or `text-slate-600`.
  Text on an orange fill is `text-on-hot`; `ink` is light now, so `bg-ink/..` washes
  and `border-ink` hovers glare
- **Type:** Inter for text, Geist (`font-head`) for headings, JetBrains Mono for code,
  paths, data and `.tag` micro labels. All three are bundled
- **Icons:** `<Icon name>` from `lib/icons.tsx` (Lucide; register a name there first),
  `<BrandMark name>` from `lib/brands.tsx` (simple-icons, contrast-checked), node kinds
  from `lib/kinds.ts`. Kind and brand colours are data in those tables, nowhere else
- **Motion** goes through `lib/motion.ts` (`useReducedMotion`, `useCountUp`, `useFill`)
- **Building blocks** in `components/primitives.tsx` (`IconTile`, `Pill`, `ListRow`,
  `StatBlock`, `CountUp`, `CodebaseMark`) and the `.tbl` table. Lists and tables, not
  grids of identical cards
- three.js is imported only by `components/atlas/`, which the router loads lazily;
  keep it that way, or the main chunk carries 580 KB of 3D for every page
- Everything under `ui/src/app/` is the application. `lib/` holds the API client, types,
  formatters and the stage-narration table; `components/` and `pages/` the rest
- API base URL comes from `VITE_API_URL` (set in `ui/.env.local`), defaulting to `:8000`
- **Tabs.** The studio keeps a tab per codebase, per conversation and one for the lists
  (`components/layout/Tabs.tsx`; which tab a navigation belongs to is decided in
  `tabState.ts`). The routes under `/app` live in `routes.tsx`, and every tab renders
  them with its own location inside React's `<Activity>`: a hidden tab keeps its state
  but **its effects stop** (no polling, no 3D drawing), and a navigation from a hidden
  tab moves only that tab. Don't write a page that needs an effect to keep running while
  another tab is showing
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
make test          # full suite — ~30 seconds, starts nothing
pytest tests/unit/ # unit only
pytest tests/integration/ # a temporary SQLite file; no services to bring up
```
