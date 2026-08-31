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
codebase is understood. The phase tracker for this work completed and was deleted; see
[.dev/STATUS.md](.dev/STATUS.md) for where things stand.

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

Tracker completed and was deleted; the studio conventions live in `CLAUDE.md`.

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

## Phase 6 — Documentation sites ✅

The output model changed from *a document per job* to **one living documentation site
per project**, grown a section at a time — top-level sections, real `.md` pages beneath
them, headings inside each page. The site map is decided during analysis, so a section
generated months later slots into a navigation that already expected it.

Phases S1–S6 all landed; the plan that tracked them completed and was deleted.
Decisions taken: our own UI and theme (MkDocs and Docusaurus stay export targets), the
map is analysis-driven, and it was built in stages with the single-document path working
throughout.

- **S1** — schema and site map: `doc_sites`, `doc_pages`, `site_planner` during analysis
- **S2** — page-based generation; `page_slugs` scope on `POST /{id}/compose`
- **S3** — the site UI: reader, nav, per-page status, generate-from-nav
- **S4** — incremental growth: `SiteService.merge_proposal`, dirty-checked, never deletes
- **S5** — staleness and provenance, per-page QA
- **S6** — export tree, static HTML, and frozen versions (`version_id IS NULL` is live)

Three things that bite: `version_id IS NULL`
is the live site and uniqueness is two *partial* indexes; slugs are permanent and a
dropped page becomes `orphaned`, never deleted; `anchor_id` in `app/knowledge/sites.py`
and `anchorId` in `ui/src/app/lib/site.ts` must produce identical strings.

---

## Phase 7 — Windows support, and the C1 baseline ✅

### The worker never ran a task on Windows

Three defects, each invisible on POSIX and none catchable by the test suite. They are
recorded together because the first masked the second and the second masked the third.

- **Celery's prefork pool needs `fork()`.** Windows spawns instead, and the child never
  inherits the module globals `celery.app.trace.fast_trace_task` reads — every task died
  on pickup with `not enough values to unpack (expected 3, got 0)` while the worker
  printed its queues, its task list and `ready`. A booting worker and a working one look
  identical. `app/workers/celery_app.py` now sets `worker_pool = "solo"` on win32, as
  config rather than a CLI flag so it reaches `dev.sh`, `make worker` and a bare
  `celery … worker` alike
- **`asyncio.get_event_loop()` in all five task entrypoints** worked only by accident of
  prefork's implicit main-thread loop. `asyncio.run()` is not the fix: the SQLAlchemy
  engine pool and the `@lru_cache`d `AsyncOpenAI` httpx pool are bound to the loop that
  created them, so a fresh loop per task breaks the *second* task somewhere far from the
  cause. New `app/workers/runner.py` keeps one loop per thread — the lifetime prefork
  used to provide, made explicit
- **Every stored path used `\` separators**, which silently defeated `registry.should_skip`:
  `PurePosixPath("node_modules\\x.py")` has one part, so no vendored directory was ever
  skipped and `node_modules` / `.venv` would have been parsed, embedded and stored. Paths
  are normalised with `.as_posix()` at all seven sites, and `should_skip` splits both
  separators as a backstop. This was the one the two failing unit tests were pointing at

**Why `solo` and not `threads`:** the two loop-bound singletons above would then be shared
across four worker loops, and making them thread-local is a real refactor that buys
nothing — one LM Studio instance serves requests serially. Concurrency *within* a job is
untouched; the `asyncio.gather` over modules still runs 6-wide.

Also: Python floor lowered `>=3.12` → `>=3.11` (plus `ruff` target and `mypy` version) to
match the conda env in use; nothing in `app/` uses 3.12-only syntax. And
`scripts/test_embedding.py` had its own `.env` parser that did not strip inline comments,
so it reported a false `[FAIL]` against a perfectly good endpoint.

### C1 — the post-fix composition baseline

Measured on **job #4**, `architecture` composed as one section job (4 pages, 570s).
Full results and the re-scoping of C4/C5 in
the composition plan, since completed and deleted. The three findings that change what
gets built next:

- **The `$already_written` fix works and did not solve the problem.** 64 `[[ ]]` refs
  emitted with real cross-page links on every page — those addresses exist nowhere but
  the neighbour list, so it reached the model. `overview-2` still restates its neighbours,
  in four broad headings instead of five narrow ones. **C4 stays a rescue, not an
  optimisation**
- **C5's heading-cap bullet is void.** Every page planned exactly 4 `##` against a cap of
  6. The length driver is **594 words per heading vs 555 pre-fix** — the number that has
  never moved. The word budget is C5's only real lever. The writer also adds 13–24 `###`
  per page that nothing asked for
- **Per-page time is unchanged** (142s vs 140s). The 72s of redundant `strategy` calls is
  real and gone (6.0s for one section job), but that is a **job-scope** win available
  today, not something the prompt fix bought

*Caveat recorded with the numbers: this is a post-fix baseline on different models
(`qwen/qwen3.5-9b`, `liquid/lfm2.5-1.2b`) and a freshly planned map, not a controlled A/B
of the fix.*

---

## Phase 8 — C2–C5: composing into the site ✅

Tracker and full measurements were in the composition plan, since completed and deleted.
Measured on job #5 against C1's job #4 — same section, same four pages, same models.

- **C2 — progress where the work is happening.** The docs reader derives "being
  written" from `doc_pages.job_id` and `status`, not from which button you pressed, so
  it is right in a second tab and after a reload. New `PageProgress` polls the job with
  the same discipline `useJob` already had, narrates the stage, links to the run, and
  reloads both the map and the open page when the job lands. A page whose worker died
  now reads as **stalled with a retry** instead of spinning for ever. The job page lists
  the addresses it is writing
- **C3 — the reading column.** The section nav moved inside the centred column, bordered
  like the document and mirroring the heading ToC on the other side; larger entries.
  Both side columns collapse above the prose below `lg`
- **C4 — one plan per section.** New `SECTION_PAGE_PLAN` allocates headings across every
  page of a section in one call. Per-page planning stays as the fallback and fires on a
  failed call, an unusable response, *or* a page the model forgot. `key_files` are still
  validated against the whole KB
- **C5 — pages the size of pages.** `SECTION_WRITE` reframed: it now says which page and
  which heading, carries `SITE_WORDS_PER_HEADING` (350) and
  `SITE_MAX_SUBHEADINGS_PER_SECTION` (3), and adds an overview-page steer. The linker
  demotes markdown links to source paths — the C1 defect — to backticked code

| | C1 (job #4) | C4+C5 (job #5) | |
|---|---|---|---|
| Words per page | 2,376 | **1,249** | −47% |
| Words per `##` | 594 | **312** | −47% |
| `###` subheadings | 75 | **39** | −48% |
| Planner calls | 4 | **1** | |
| **Dead links published** | **19** | **0** | |
| Wall clock | 570s | 626s | **+10%** |

**C4's saving is real, and the run that appeared to disprove it was a reasoning loop.**
Replaying both prompts: one page = 49.6s, one section = 58.7s, so four page calls ≈ 198s
against one section call at 59s. The measured 221.3s was `qwen3.5` looping in its own
thinking — repeating "Wait, checking the Overview content again" until it hit
`LLM_MAX_TOKENS`, returning empty, and being retried three times **inside one traced
span**, which is why it read as a single slow call.

The finding underneath it is the reusable one: **a reasoning model emits ~4,700 tokens
of thinking per call whatever the task size** — a single-page plan whose stored JSON is
337 tokens cost 5,086 completion tokens. That overhead is fixed, per call, and invisible
in the artifacts, which store the parsed result. Three fixes landed: the section prompt
no longer asks the model to verify `key_files` membership (the loop trigger — `_validate`
already drops unknown paths), `chat_completion` now counts `reasoning_content` and logs
`llm_thought_but_did_not_answer`, and `LLM_MAX_TOKENS` went 8192 → 12288.

**C5 overshot its own target** — 312 words per heading against a 350 budget, with the
heading count untouched, confirming C1 read the mechanism right. `overview-2` went from
2,299 words with 8 outgoing links to **1,237 with 24**: half the length, three times the
links out, which is what an overview page is supposed to do.

Two regressions recorded rather than smoothed over: wall clock up 10%, and
`state-management`'s QA fell 7.0 → 5.0 — the only page that dropped, and exactly the
"thin rather than padded" risk C5 named. 222 unit tests pass.

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
- **Nothing validates a plain markdown link.** The linker checks `[[ ]]` addresses and
  heading anchors; a relative-path link is not checked by anything. C1 found
  `architecture/data-model` published with **19 of 28 links dead** — source paths used as
  hrefs, some carrying a stray backtick inside them, e.g.
  ``[`TracerConfig`](`neurosurfer/tracing/config.py)``. Concentrated on one page of four,
  so it is a drift the writer falls into rather than a systematic failure. Tracked as a
  C5 item
- **Overview-shaped pages still shadow the rest of the site** even with the
  anti-duplication instruction rendering — see C1. The allocation is made by independent
  per-page planning calls, and no instruction to the writer can undo it; that is what C4
  is for
- **CI and the Dockerfile still pin Python 3.12** while the declared floor is now 3.11,
  so the version actually developed on is never exercised. One line each in
  `.github/workflows/ci.yml`, `.gitlab-ci.yml` and `Dockerfile`
- **`ui_backup/` is still parked** and wired to nothing; `CLAUDE.md` says delete it once
  nothing cross-references it, and nothing does

---

## Local Dev Setup

```bash
cp .env.example .env          # fill in values
make infra                    # postgres, redis, minio, neo4j, prometheus, grafana
make migrate                  # apply DB migrations — through a91b6d47c052
make seed                     # admin@docany.dev / admin1234
./dev.sh                      # Celery worker + hot-reload API on :8000
cd ui && pnpm install && pnpm dev     # studio on :5173, needs Node >= 20.19
```

`make dev` does not exist — `dev.sh` is the entry point, and it starts *both* the worker
and the API. It picks `.venv` when there is one, else conda `$CONDA_ENV` (default `LLMs`).

**The embedding model and `VECTOR_DIMENSIONS` are one decision.** The value is read at
migration time and baked into `code_chunks.embedding`; changing it later means re-running
`alembic upgrade head`, **which TRUNCATEs `code_chunks`**, and re-ingesting every project.
Current local setup is `text-embedding-nomic-embed-text-v1.5-embedding` at **768** dims.

```bash
conda run -n LLMs python scripts/test_embedding.py   # checks reachability + dims + similarity
```

### ⚠️ The Celery worker does not auto-reload

The API runs with `--reload` and picks up changes; **the worker does not**. It has already
cost two sessions — fixes sat in the tree while jobs ran the old code and the results were
measured as if they were current. **Restart the worker after any change to `app/`**,
especially agents, prompts or workflows.

Integration tests need their database to exist first:

```sql
CREATE DATABASE documentanything_test;
\c documentanything_test
CREATE EXTENSION IF NOT EXISTS vector;
```
