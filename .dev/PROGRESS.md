# Rearchitecture Progress

Execution tracker for [PLAN.md](PLAN.md). Update the status column as work lands;
keep notes on anything that contradicted the plan.

Legend: ⬜ not started · 🟨 in progress · ✅ done · ⛔ blocked · ⏭️ deferred

## Summary

| Phase | Scope | Status |
|---|---|---|
| A | Knowledge Base data model + persistence | ✅ |
| B | Analysis workflow (Phase 1 of the product) | ✅ |
| C | Composition workflow (Phase 2 of the product) | ✅ |
| D | API + UI two-step flow | ✅ |
| E | Performance + cleanup | 🟨 E1 and E5 done; E2–E4 open |

A separate UX overhaul (U1–U7) ran after Phase D and is complete — see
[UX_PLAN.md](UX_PLAN.md) / [UX_PROGRESS.md](UX_PROGRESS.md). It also landed real
cancellation, which is a backend change this tracker did not plan for.

Two further bodies of work have landed since, tracked in their own documents rather than
here: **S1–S6** (documentation sites, complete — [SITE_PLAN.md](SITE_PLAN.md)) and
**C1** (the post-fix composition baseline — [COMPOSITION_PLAN.md](COMPOSITION_PLAN.md),
where C2–C5 remain open). E2–E4 below are still the oldest open items in the repo.

## Phase A — Data model and persistence ✅

Completed 2026-08-04. 48 tests pass (20 new unit, 21 new integration); ruff clean.

| # | Task | Status | Notes |
|---|---|---|---|
| A0 | `app/languages/` — language abstraction seam | ✅ | added scope: see below |
| A1 | `app/models/knowledge.py` — KB, KBModule, KBEntity, KBNarrative | ✅ | |
| A2 | `kb_id` on `code_chunks`; `job_type` on `jobs` | ✅ | `job_type` defaults to `composition` for back-compat |
| A3 | Alembic migration + downgrade | ✅ | `32dafb55b4af`; upgrade→downgrade→upgrade verified |
| A4 | `app/db/repositories/knowledge/` (upsert by project+commit) | ✅ | package of 4 repos + `KnowledgeRepositories` bundle |
| A5 | `app/schemas/knowledge.py` | ✅ | incl. `KnowledgeBaseSummary`, `DocTypeSuggestion` |
| A6 | Repository tests | ✅ | 21 integration tests |

### Language abstraction (added to Phase A)

Scope added after the multi-language requirement: the DB schema is where language
assumptions get baked in permanently, so the vocabulary had to be settled before the
migration, not after.

```
app/languages/
  taxonomy.py            SymbolKind · Visibility · ModuleKind   (language-neutral)
  base.py                LanguageProvider ABC · Symbol · ModuleRef
  registry.py            path → provider lookup, shared ignore list
  providers/python.py    PythonProvider (stdlib `ast`, not regex)
app/knowledge/
  constants.py           KBStatus · EntityKind · NarrativeTopic · ModuleRole · JobType
```

Everything language-specific sits behind `LanguageProvider`: which files belong to a
language, what a declaration looks like, how files group into modules, what counts as
a test or an entrypoint. `test_registry.py::test_adding_a_language_needs_only_registration`
pins that contract with a fake Go provider.

Nothing in the KB schema names a language — `language` is a free string from whichever
provider handled the file, and symbol/entity kinds come from the neutral enums.

### Deviations from plan

- **Models are one module, not a package.** `app/models/knowledge.py` holds all four,
  matching `job.py` (which holds three). A package would have broken the convention for
  no gain.
- **Test fixtures moved.** `tests/conftest.py` had an `autouse=True` session fixture
  that forced a DB connection on *every* test, contradicting `make test-unit`
  ("no infra needed"). DB fixtures now live in `tests/integration/conftest.py`.
- **pytest-asyncio 1.x.** The custom `event_loop` fixture is removed in 1.x and caused
  "attached to a different loop"; replaced with `asyncio_default_*_loop_scope` in
  `pyproject.toml`.
- **Test DB URL now derives from settings** instead of hardcoding port 5432, which no
  longer exists on this machine.

### Landmine to remember

`alembic revision --autogenerate` proposes **dropping `ix_code_chunks_embedding`** every
time — the pgvector HNSW index was created by hand in `0001` and is invisible to
SQLAlchemy metadata. It is commented in `32dafb55b4af`. Never accept that drop.

## Phase B — Analysis workflow ✅

Completed 2026-08-04. 85 tests pass; ruff clean on all authored files.
**Validated end-to-end against a real repo with `qwen/qwen3.5-9b`** — not just unit-tested.

| # | Task | Status | Notes |
|---|---|---|---|
| B1 | `analysis_workflow.py` + `AnalysisState` | ✅ | state has no `doc_types` — pinned by a test |
| B2 | `structured_extractor` (no LLM) | ✅ | opens the KB, writes modules + facts; **0.07s** |
| B3 | `module_summarizer` (fan-out) | ✅ | bounded concurrency + module cap |
| B4 | `architecture` → `architecture_synthesizer` | ✅ | no ReAct; fallback now derived from real facts |
| B5 | `narrative_writer` (fan-out per topic) | ✅ | topics chosen from evidence |
| B6 | `kb_persister` | ✅ | stats, suggestions, READY/DEGRADED |
| B7 | Batch embeddings | ✅ | **30.7s → 8.5s** measured |
| B8 | Fix cache-hit returning full state | ✅ | `code_understanding.py` now returns `{}` |
| B9 | Celery task `analysis.run_analysis` | ✅ | routed to the `ingestion` queue |
| B10 | Skip re-analysis when a ready KB exists | ✅ | `force` overrides |

### Measured on a real run

Analysis of `app/` (146 files) against `qwen/qwen3.5-9b`, **571s total**:

| Stage | Time | Note |
|---|---|---|
| repo_analyzer | 0.04s | |
| structured_extractor | **0.07s** | deterministic — 29 modules, 31 facts |
| semantic_indexer | **8.5s** | was ~30.7s serial; 365 chunks |
| module_summarizer | 445s | 29/29 summaries, concurrency 4 |
| architecture_synthesizer | 75s | one grounded call |
| narrative_writer | 83s | 5/5 topics after the fix below |
| kb_persister | 0.02s | |

Result: **29 modules · 31 entities (28 routes, 2 entrypoints, 1 env var) · 365 chunks ·
5 narratives · status READY**, with suggestions `api (0.95), architecture (0.90),
getting_started (0.70), modules (0.60)` — driven by the routes actually found.

The important number is not 571s but that a *second* document type now costs only its
composition. Everything above is paid once per commit.

### Bugs found and fixed during the run

1. **Concurrent `AsyncSession` use lost 4 of 5 narratives.** `narrative_writer` read its
   supporting facts from the DB *inside* the `asyncio.gather`, so several tasks shared one
   session — asyncpg raises "another operation is in progress". Facts are now fetched
   sequentially before the concurrent phase; verified 1/5 → **5/5**. Pinned by
   `test_concurrent_topics_all_succeed`.
2. **`gather(return_exceptions=True)` swallowed the cause.** Failures were counted but never
   logged, which is why the above looked like a mystery. Both fan-out agents now log the
   exception *and* name the module/topic that produced it.
3. **Decorator arguments were being discarded.** `_decorators` unparsed only the callee, so
   `@router.get("/x")` became `router.get` and no route was ever detected. Fixed → 28 routes.
4. **Manifests were unreachable.** `pyproject.toml` was looked up by extension, which no
   provider owns, so dependencies were never parsed. Added `registry.manifest_providers()`
   (filename-based) → 46 dependencies.

### Language layer extended

Two optional provider hooks, both defaulting to no-op, so entity extraction stays behind
the seam rather than leaking `if language == ...` into the extractor:

- `detect_entities(path, source, symbols)` — routes, env vars, entrypoints
- `parse_manifest(path, source)` — declared dependencies

`PythonProvider` implements both. Adding Go means writing them there, changing nothing else.

### Deviations from plan

- **`code_understanding` was not modified in place.** The analysis path gets a new
  `semantic_indexer`; the old agent stays for the current documentation workflow until
  Phase C replaces it. Its cache-hit bug (B8) was still fixed.
- **Fan-out is in-agent, not in-graph.** `module_summarizer`/`narrative_writer` use a bounded
  semaphore rather than LangGraph `Send()`. Cheaper, and it keeps one DB session per stage —
  which, as bug 1 shows, is the thing to be careful about.
- **Domain logic lives in `app/knowledge/builder.py`**, not in the agents: pure functions, no
  DB, no LLM, 23 unit tests, runs in 0.04s.

## Phase C — Composition workflow ✅

Completed 2026-08-04. 101 tests pass; ruff clean on all authored files.
Validated end-to-end — see `.dev/runs/20260804-123616/00_REPORT.md`.

| # | Task | Status | Notes |
|---|---|---|---|
| C1 | `composition_workflow.py` + `CompositionState` from KB | ✅ | back half (diagram/qa/formatter/publisher) reused |
| C2 | `planner` reads KB | ✅ | validates `key_files` against the KB; drops hallucinated paths |
| C3 | `strategy` reads KB narratives | ✅ | |
| C4 | `app/knowledge/retrieval.py` — `SectionContextBuilder` | ✅ | moved from `app/agents/` — see deviations |
| C5 | Writer → retrieve-then-write; per-section ReAct gone | ✅ | one LLM call per section |
| C6 | Bounded escape hatch | ✅ | `NEED_CONTEXT:` marker, exactly one retry |
| C7 | Parallelise sections within a doc | ✅ | contexts built first, then concurrent generation |
| C8 | Celery task `composition.run_composition` | ✅ | routed to the `generation` queue |

### Measured

Analysis **171.9s** (was 571s) → KB with 30 modules, 31 facts, 5 narratives.
Composition **~440s** → architecture (40k chars) + API (30k chars), 7 sections each.

The re-composition reused the same KB with **no re-analysis** — the split working as
designed. Each extra document type costs only its own composition.

### The model-tiering finding (Phase E1, pulled forward)

`select_model()` tiering had been a no-op — all three env vars named the same model.
With `LLM_FAST_MODEL=liquid/lfm2.5-1.2b`:

- **module_summarizer: 445s → 7.8s (57×)**, with no loss of quality. Summarising is
  bounded and mechanical; qwen was spending ~12s per module thinking first.
- **planning on the small model was unusable**: for `doc_type="api"` it returned
  architecture-shaped sections, a title of "Documentation Architecture", and
  **zero `key_files` on every section**. Since retrieve-then-write anchors retrieval on
  those paths, the API document silently came out generic.

`plan` was therefore moved from `fast_tasks` to `quality_tasks`. Cost ~60s per doc type;
it fixes the document's whole structure and all downstream retrieval.

Lesson worth keeping: **tier by whether the task needs judgement, not by output size.**
Planning produces a few hundred bytes of JSON and is the most consequential call we make.

Follow-up A/B on the two remaining expensive analysis stages (same KB, both models):

| stage | lfm2.5-1.2b | qwen | verdict |
|---|---|---|---|
| architecture synthesis | 4.6s — valid JSON, 14 services but only **2 layers** | 26s — 9 services, **13 layers** | keep on quality |
| narrative (architecture) | 1.5s — 1,932 chars, cites 16 modules | 36.4s — 6,706 chars, cites 22 | keep on quality |

Both stay on quality deliberately. Module summaries are per-module and bounded, so a thin
one hurts one module; narratives and the architecture map are read by every plan, every
narrative and every section of every document type. A 3.5× thinner narrative degrades
everything downstream for a one-time saving that is already paid once per commit.

Refined rule: **fast tier for bounded mechanical work; quality tier for anything reused or
structural.** Instead, `ANALYSIS_SUMMARY_CONCURRENCY` went 4 → 6 (untested at that value):
5 narrative topics at 4-way concurrency is two serial batches, so this should take the
stage from ~83s to ~45s with no quality change.

### Bug found while A/B-ing: the KB recorded zero dependencies

The "is this framework grounded?" check flagged FastAPI and Celery as invented — because
`kb_entities` held **no dependencies at all**, despite the sample repo's `pyproject.toml`
declaring 46.

Cause: `CodeParser.parse_directory` only yields files whose extension maps to a language,
so `pyproject.toml` never entered `codebase.files` and `parse_manifest()` never ran. The
manifest hook added in Phase B was correct but starved of input.

Fixed with `read_manifest_files(repo_root)`, called from `structured_extractor` using
`repo_path`. Verified: 46 dependencies now extracted. Four regression tests cover
discovery, nesting, vendored-directory skipping, and a missing root.

This also mattered beyond counts: the architecture prompt says *"do not add frameworks that
do not appear in the dependency list"* — an instruction that was meaningless against an
empty list.

### Deviations from plan

- **Retrieval lives in `app/knowledge/retrieval.py`**, not `app/agents/retrieval.py` — it
  is knowledge-base logic, reusable outside the agents, and testable on its own.
- **Composition reads source from `code_chunks`, never the filesystem.** By Phase 2 the
  analysis job's cloned repo is gone; the stored chunk text *is* our copy of the source.
  This is what makes composition runnable as an independent job.
- **A `kb_loader` agent was added** (not in the original plan) to resolve which KB to
  compose from and fail loudly when a project has never been analysed.
- **Planner validates `key_files`** against the KB. Unlisted paths are dropped rather than
  passed on, because a hallucinated path retrieves nothing and yields a section written
  from thin air.
- **Document titles are validated.** One planner run returned literally `"api"` as the
  title; there is now a deterministic fallback.

## Phase D — API and UI ✅

Completed 2026-08-04. 105 tests pass; UI builds clean; verified end-to-end in a browser
with a real analysis (job 24) and composition (job 25) driven through the UI.

| # | Task | Status | Notes |
|---|---|---|---|
| D1 | `POST /projects/{id}/analyze` | ✅ | 202; takes no doc type by design |
| D2 | `GET /projects/{id}/knowledge-base` | ✅ | returns null when never analysed |
| D3 | `POST /projects/{id}/compose` | ✅ | refuses without a usable KB |
| D4 | Back-compat for `POST /projects/{id}/jobs` | ✅ | legacy single-shot kept for API clients |
| D5 | UI: KB state on project detail | ✅ | polls while building |
| D6 | UI: doc-type picker gated on KB ready | ✅ | suggestions with confidence + evidence |
| D7 | UI: re-analyse action | ✅ | |

New: `app/services/knowledge_service.py` (business logic), `KnowledgeBasePanel`,
shared `Card`/`Badge` primitives, `lib/format.ts` (durations, acronym-aware `humanize`).

### UI work beyond the plan

The existing pages were functional but rough, so alongside D5–D7:

- **Card / Badge primitives** — every page previously rolled its own border, padding and
  pill styling. Badges now use theme-aware tones; the old `bg-gray-100 text-gray-600`
  pills were nearly invisible on the dark background.
- **Durations everywhere** — job list "Took" column, per-agent step timings, and a header
  clock that ticks live while a job runs. This is real data: Phase B started recording
  `started_at`/`completed_at` per step.
- **Live events** — the job page already streamed via SSE; it now also shows the phase
  badge, correct agent names and elapsed time so the stream has context.
- **Removed the competing "Run Documentation Job" buttons.** The legacy single-shot path
  contradicted the two-phase flow. The endpoint remains for API clients.

### Bugs found by looking at the running UI

1. **Pipeline panel showed the wrong agents.** `AGENT_PIPELINE` was one hardcoded list, so
   an analysis job displayed the composition agents as pending with the real ones appended
   underneath. Now keyed by `job_type` (`analysis` / `composition` / `legacy`).
2. **A completed analysis job offered "View Documents"** and claimed documentation was
   generated. Analysis produces a knowledge base; it now links onward to choose what to write.
3. **"Api" instead of "API"** — `humanize()` gained an acronym set.
4. **Architecture synthesis regressed to DEGRADED.** Raising summary truncation to 400
   chars was fine, but the manifest fix added 46 dependencies and the prompt asked the
   model to echo them all back. The JSON truncated mid-array at the same point on all
   three retries — ~650 output tokens, so it is the model's loaded context in LM Studio,
   not our `LLM_MAX_TOKENS=8192`. Fixed by capping what the prompt asks for
   (≤8 external deps, ≤10 services, ≤6 layers) and trimming the input list to 30.
   Verified in isolation: valid JSON, 8 services / 4 layers / 8 deps.

**Worth checking:** the loaded context length for `qwen/qwen3.5-9b` in LM Studio. If it is
4096, every quality-tier call is tighter than the config implies.

## Phase E — Performance and cleanup 🟨

| # | Task | Status | Notes |
|---|---|---|---|
| E1 | Real `LLM_FAST_MODEL` | ✅ | `liquid/lfm2.5-1.2b`; module summaries 445s → 7.8s. `plan` had to move to the quality tier — see the A/B above |
| E2 | `diagram` opt-in per doc type | ⬜ | 64s / 15% of run 18 |
| E3 | Neo4j decision (fold into KB or drop) | ⬜ | built every run, queried never |
| E4 | Human-review gate resumption via interrupt | ⬜ | currently `END`, cannot resume |
| E5 | Remove `react_mixin` from the writer path | ✅ | done by C5. `ReActMixin` now only serves `documentation_workflow`'s legacy `writer` and `architecture` agents |

## Baseline to beat

Measured on **run 18** (1 architecture doc, 16,608 chars, 430s wall):

| Agent | Time | Share |
|---|---|---|
| writer | 237.7s | 55% |
| diagram | 64.2s | 15% |
| planner | 56.3s | 13% |
| qa | 49.9s | 12% |
| code_understanding | 30.7s | 7% |
| strategy | 24.1s | 6% |
| architecture | 16.0s | 4% |

Tool calls in that run: `read_text_file` × 21, `search_codebase` × **0**,
`query_code_graph` × **0**. 127s (30%) elapsed before the first word was written.

### After Phases B–C + E1

| Stage | Before | After |
|---|---|---|
| Analysis (whole phase) | 571s | **171.9s** |
| — module summaries | 445s | **7.8s** (fast tier + concurrency) |
| — embedding | 30.7s | **8.5s** (batched) |
| Composition, 2 doc types, 7 sections each | — | ~440s |
| Second doc type on an existing KB | full re-analysis | **composition only** |

The last row is the one that mattered. The target was never just "faster" — it was that a
*second* doc type costs only its composition, because analysis is already done. It does.

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-08-04 | Dropped CodeGraph | Evaluated at `test_codegraph/`. Indexing is excellent (247 files / 195ms) and symbol-targeted queries are accurate, but prose queries were wrong in 2 of 6 cases and it has no embeddings, so it could not replace pgvector. Not worth the Node/Rust dependency. |
| 2026-08-04 | Split analysis from composition | Doc type should be chosen *after* the codebase is understood; analysis is expensive and doc-type-independent. |
| 2026-08-04 | Writer gets bounded retrieval, not a ReAct loop | Run 18 showed the loop re-reading files and never using retrieval, at 55% of runtime. Keep the capability, cap the cost. |
