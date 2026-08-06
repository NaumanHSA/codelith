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

## Phase 5 — Findings from runs 1 and 2, fixed ✅

Read the two runs artifact by artifact, wrote down what was wrong, then fixed all of
it. Verified on a live re-analysis (job 3) and composition (job 4) of the same
repository, so every number below is measured rather than expected.

| | before | after |
|---|---|---|
| Modules inferring to `unknown` | 23 of 45 (13,770 LOC) | **0** |
| Narratives written | 6 | **11** |
| Section context used, opening section | 1,930 / 6,000 tokens (32%) | **5,872 (97%)** |
| Module summaries reaching a section | 1–2 of 44 | **8–9** |
| Narratives reaching a section | 1 | **4** |
| `key_files` surviving validation | 1 of 3 | **3 of 3, every section** |
| Junk entrypoints | 5 of 10 | **0 of 3** |
| Chunks whose line metadata overstated their text | 378 (34%) | **0** |
| Diagrams reaching the document | 0 | **2** |
| Architecture map available to composition | never | **persisted, with 6 relation edges** |

### Role classification — `app/knowledge/roles.py`

The single highest-value fix: role gates narrative selection, the planner's module
inventory and the planner's `key_files` validation, so a misclassified module was
invisible three times over. Three causes, all addressed:

- **Evidence now outranks convention.** A module whose files define HTTP routes is the
  API layer whatever the directory is called; infra resources likewise.
- **The leaf outranks its ancestors.** `app/server/schemas` was called `api` because an
  ancestor said `server`; it is a schema package.
- **Plurals are matched by expanding hints, not stemming segments.** `workflows` never
  matched `workflow`; a stemmer had turned `vectorstores` into `vectorstor`.
- **`unknown` is now earned.** Unmatched code with public symbols falls back to
  `service`; `unknown` is reserved for modules with nothing to go on.
- Filename hints must *dominate* a module — one `config.py` among thirteen files had
  been relabelling an entire RAG package as `config`.

19 regression tests in `tests/unit/knowledge/test_roles.py`, each a real miss from run 1.

### Narrative topics — `app/knowledge/narratives.py` (new)

- Vocabulary widened from 10 topics to 17, covering CLIs, libraries, frontends and
  pipelines rather than assuming a request/response service.
- Selection is a **deterministic floor plus a fast-tier proposal**. The floor is what
  the extracted facts justify and cannot be talked out of; the selection call may add
  topics, and its output is coerced onto the enum so an invented topic name is dropped
  rather than written where no consumer will look for it.
- `error_handling` is reachable — it was in the enum with prompt guidance written for
  it and in no trigger table at all.
- `auth` no longer fires on any module containing "token".
- Capped by `ANALYSIS_MAX_NARRATIVES` (12), since each is a quality-tier call.

**Observed on job 3:** the floor produced all 11 topics and the selection call proposed
nothing usable on `liquid/lfm2.5-1.2b` — the same lesson as the earlier `plan` finding
(*tier by whether the task needs judgement, not by output size*). The floor covering it
is the designed failure mode working, but the selection call is currently contributing
nothing; try it on the quality tier before concluding it earns its keep.

### Narrative delivery

- `DOC_TYPE_TOPICS` is now the single source of truth for strategy, the planner and
  section retrieval. Strategy used to read `overview` + `architecture` regardless of
  what was requested, which is why an API document's strategy call saw zero occurrences
  of "endpoint" while the endpoint list sat in the `request_lifecycle` narrative.
- The flat `[:1500]` truncation is replaced by per-consumer budgets: strategy and the
  planner read narratives whole (one call per job), section context still bounds them.
- The narrative prompt now optimises for **information per character** — concrete paths,
  symbols, routes and counts — and forbids the filler that survives any codebase. The
  architecture narrative went 5,147 → 2,664 chars covering the same ground.
- `REACT_CONTEXT_WINDOW_LIMIT` raised 6000 → 14000 to match the code's intent; at 6000
  it silently trimmed the front of any prompt carrying full narratives.

### Section context — starved, not trimmed

- **`_validate()` checks against the whole KB**, not the role-filtered slice shown to
  the planner. Run 2 lost two of three anchor files for its opening section — both real
  KB paths — leaving that section 15 lines of source.
- Module summaries cover the files retrieval surfaced, not only the files the planner
  named: 1–2 of 44 became 8–9.
- Retrieval over-fetches once and **fills toward the budget** instead of stopping at a
  constant 6 blocks.

### Diagrams — `app/agents/diagram.py`, `app/tools/mermaid.py` (new)

- The set is **derived** from the document type and the facts the KB holds, each
  candidate gated by a precondition. "Nothing worth drawing" is an ordinary outcome,
  which subsumes E2.
- Nodes are **grounded**: the prompt receives the exact vocabulary it may label with —
  real services, modules, routes — plus the `relations` edges the map now carries. Run 2
  had invented `Workers`, `Storage`, `Data Ingestion` and a `Feedback Loop` for a
  codebase with none of them.
- Output is **validated** structurally, repaired once, and dropped if it still fails.
  Both of run 2's diagrams are rejected by it, including a `class Foo --` malformation
  caught only after seeing job 4 produce one.
- Diagrams are injected into the document they were drawn for, not only `architecture`.

### Diagram rendering, and why the stage ships disabled

Mermaid source in a fenced block is only a picture if the reader renders Mermaid, and
neither the studio's markdown pipeline nor a DOCX export does — so diagrams arrived as
walls of `graph TD` text. Diagrams are now rendered to PNG locally
(`@mermaid-js/mermaid-cli` + headless Chrome, both installed by the root
`package.json`, so no network at job time), embedded in the document as a data URI,
and the Mermaid source is kept beneath in a collapsed block. Source and picture are
also written side by side to `runs/{job}/outputs/diagrams/`.

Getting there took five live runs and each one taught something:

| run | outcome | cause |
|---|---|---|
| 5 | invented `LoginPage`, `Customer`, `P1` | the one-shot example was copied for its *content* |
| 6 | both diagrams dropped | the fast tier cannot draw a grounded diagram |
| 7 | dropped `P_SERVER` as invented | **our bug** — grounding-checked participant *handles*, not their aliases |
| 9 | one rendered, one dropped as `P4-` | **our bug** — the edge regex ate the arrow's first dash |
| 10 | both empty after 3 retries | `diagram` ran concurrently with `qa`; one local model, two requests |
| 11 | **both rendered and embedded** | after serialising diagram → qa |

Changes that came out of it, all kept:

- `diagram` moved to the quality tier, alongside `plan` and `select`. Third time the
  same lesson: **tier by whether the task needs judgement.**
- Label grounding is enforced, not just requested: `ungrounded_labels()` rejects a
  diagram naming anything outside the supplied vocabulary, with participant aliases
  and Mermaid-safe spellings (`a_b` for `a.b`) understood.
- The renderer is the final validator — it is the only true Mermaid parser we have,
  and it catches what a structural check cannot (a dotted participant id parses fine
  to us and not to Mermaid).
- An empty completion is now a **retryable failure** in `BaseAgent._chat_with_retry`.
  It is not an error the transport reports, and it silently produced nothing twice.
- `diagram` and `qa` no longer run in parallel. The parallelism saved wall time and
  cost every diagram in the document.

**The stage is off by default** (`DIAGRAMS_ENABLED=false`). It works, but each diagram
is a quality-tier call plus a browser render, and it is the least load-bearing thing
composition does. Everything behind the flag is complete and tested; flip it to `true`
to re-enable. A better strategy for diagrams is still worth designing.

### Also

- `architecture_json` persisted on `knowledge_bases` (migration `b7c41a9f2e10`, written
  by hand — autogenerate still wants to drop the pgvector HNSW index).
- Chunking cuts on **symbol boundaries** with line-window fallback, splits oversized
  units instead of truncating them, and reports line spans that describe the text
  actually stored.
- Entrypoint detection excludes tests, scripts, examples and tutorials.
- Strategy's `priorities` field removed — nothing ever read it.
- Truncated JSON artifacts are written as a valid envelope instead of a file that no
  longer parses.

---

## Known Issues / Next Up

- **PDF** — no formatter exists; `/documents/{id}/export` advertises it and raises
- **Standalone export** only implements Markdown; DOCX/MkDocs/Docusaurus work through a
  generation job's `output_formats` but not through the export endpoint
- **Neo4j** is populated but never queried — fold the useful edges into `kb_entities` or
  drop the service (Phase E3). The architecture map now carries its own `relations`, so
  the case for keeping it is weaker still
- **Human-review gate** returns `END` with no checkpointer, so approval cannot resume the
  graph; needs a LangGraph interrupt (Phase E4)
- **Languages** — only Python has a provider; other files are indexed for retrieval but
  contribute no extracted symbols
- **Legacy pipeline** — `documentation_workflow.py` and the agents it owns
  (`coordinator`, `code_understanding`, `react_mixin`) exist only for the old
  `POST /projects/{id}/jobs` endpoint
- **Topic selection is not earning its call** on the fast tier (see Phase 5) — either
  move it to the quality tier or drop it and keep the floor
- **Mermaid validation is structural, not a parser.** It rejects everything that has
  actually gone wrong, but a determined model can still produce something that passes
  and renders badly

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
