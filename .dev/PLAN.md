# Rearchitecture Plan — Analyse Once, Compose Many

Status: proposed · Created 2026-08-04 · Track execution in [PROGRESS.md](PROGRESS.md)

## The shift

**Today** — one job does everything, and the doc type is chosen up front:

```
job(doc_types=[...]) → clone → embed → architecture → plan → strategy → write → qa → publish
```

Every job re-derives the same understanding of the codebase. Asking for an API
reference *after* an architecture doc re-runs the entire analysis, and the two runs
disagree with each other because nothing was persisted.

**Target** — analysis is a first-class artifact, composition is cheap and repeatable:

```
Phase 1  ANALYSE      project → Knowledge Base (persisted, keyed by commit)
                      "we now know everything about this code"

              ↓  user picks: architecture? api? deployment? tutorial?

Phase 2  COMPOSE      KB + retrieval → documents
                      (repeatable per doc type, no re-analysis)
```

Two consequences worth stating plainly:

1. The expensive LLM work (understanding modules, synthesising architecture) happens
   **once** and is reused by every doc type. Today `architecture` + `planner` + `strategy`
   cost ~96s of every run and produce near-identical output each time.
2. Composition becomes fast enough to iterate on. Regenerating one section stops
   requiring a full pipeline run.

## What the Knowledge Base actually contains

This is the core of the design. The KB has three layers, cheapest first:

| Layer | Source | Cost | Example |
|---|---|---|---|
| **Structured facts** | deterministic parsers | free | routes, entry points, languages, deps, env vars, infra, symbol inventory |
| **Semantic index** | embeddings → pgvector | one pass | `code_chunks`, already exists |
| **Derived understanding** | LLM, once per commit | expensive | per-module summaries, architecture narrative, request lifecycle, data model |

The third layer is what makes Phase 2 cheap. A writer composing *any* doc type reads
module summaries and narratives rather than re-reading source.

**Keyed by `(project_id, commit_sha)`** — re-analysing an unchanged commit is a no-op.
`LongTermMemory.find_cached_job` already does this for embeddings; generalise it to the KB.

## Retrieval at write time

The KB is a summary, so it will sometimes be too thin — a section needs an exact
signature, an error string, a config key. The writer therefore gets retrieval, but
**bounded**, not as a free exploration loop:

1. **Pre-packed context (default path).** Before the LLM call, Python assembles: the
   section's KB module summaries + `key_files` source + one pgvector query on the
   section focus. One LLM call, no tools.
2. **Escape hatch.** The writer may call `search_code(query)` at most N times (default 2)
   when the packed context is insufficient. One tool, capped, returning chunks — not a
   filesystem it can wander.

This is deliberately *not* the current per-section ReAct loop. Measured on run 18:
21 `read_text_file` calls, 0 `search_codebase` calls, and one
`npx @modelcontextprotocol/server-filesystem` spawn **per section**. Writer = 55% of runtime.
The default path removes all of that; the escape hatch preserves the capability the loop
was there to provide.

## Data model

New tables (Alembic migration required):

```
knowledge_bases      id, project_id, commit_sha, status, version,
                     stats_json, created_at, completed_at
                     UNIQUE(project_id, commit_sha)

kb_modules           id, kb_id, path, language, kind, loc,
                     symbols_json, summary, role
                     -- one row per meaningful file/package

kb_entities          id, kb_id, kind, name, data_json
                     -- kind ∈ route|service|entrypoint|dependency|env_var|
                     --        infra|datastore|external_api|cli_command

kb_narratives        id, kb_id, topic, content_md, source_refs_json
                     -- topic ∈ overview|architecture|request_lifecycle|
                     --         data_model|auth|deployment|testing
```

Changes to existing tables:

- `code_chunks` — add nullable `kb_id` FK so chunks are scoped to a KB generation
- `jobs` — add `job_type` (`analysis` | `composition`), default `composition` for
  back-compat; `config_json` keeps carrying `doc_types` for composition jobs only

## Workflows

Split `documentation_workflow.py` into two graphs sharing `BaseAgent`/tracing/sandbox.

### AnalysisWorkflow (Phase 1)

```
coordinator → repo_analyzer → code_understanding ─┐
                                                   ├→ module_summarizer (fan-out, parallel)
   structured_extractor ───────────────────────────┘            ↓
                                              architecture_synthesizer
                                                          ↓
                                                  narrative_writer (fan-out per topic)
                                                          ↓
                                                    kb_persister → END
```

- `structured_extractor` — **new, no LLM.** Turns parser output + `api_specs` +
  `infra_context` into `kb_entities`. Cheap and deterministic; should be the backbone
  the LLM layers sit on.
- `module_summarizer` — **new.** Fan-out over module clusters, one small LLM call each,
  writes `kb_modules.summary`. Parallel, fast model.
- `architecture_synthesizer` — replaces today's `architecture` ReAct agent. Works from
  module summaries + structured facts rather than crawling the filesystem, so it stops
  depending on a ReAct loop that currently fails and falls back to single-shot.
- `narrative_writer` — **new.** Produces `kb_narratives` for the cross-cutting topics.
- `kb_persister` — **new.** Writes the KB transactionally, marks it `ready`.

### CompositionWorkflow (Phase 2)

```
planner → strategy → writer (fan-out per doc_type × section, parallel)
                                    ↓
                          diagram ‖ qa → gate → formatter → publisher
```

- `planner` / `strategy` read the KB instead of re-deriving. Should get much cheaper.
- `writer` uses retrieve-then-write as described above.
- Sections within a doc run in parallel (today they are serial; the only coupling is
  `written_titles` for de-duplication, replaceable by passing the full outline).

## Phases and TODOs

### Phase A — Data model and persistence
- [ ] `app/models/knowledge.py`: `KnowledgeBase`, `KBModule`, `KBEntity`, `KBNarrative`
- [ ] Add `kb_id` to `code_chunks`; add `job_type` to `jobs`
- [ ] Alembic migration + downgrade
- [ ] `app/db/repositories/kb_repo.py` with upsert-by-`(project_id, commit_sha)`
- [ ] `app/schemas/knowledge.py` — `KnowledgeBaseOut`, `KBSummaryOut`
- [ ] Unit tests for the repository

### Phase B — Analysis workflow ✅ (complete — see PROGRESS.md)
- [x] `app/workflows/analysis_workflow.py` + `AnalysisState`
- [x] `structured_extractor` agent (no LLM)
- [x] `module_summarizer` agent (fan-out, `task_type="summarize"`)
- [x] Rewrite `architecture` → `architecture_synthesizer` (KB-driven, no ReAct)
- [x] `narrative_writer` agent (fan-out per topic)
- [x] `kb_persister` agent
- [x] **Batch embeddings** — measured 30.7s → 8.5s
- [x] Fix cache-hit path returning full state instead of `{}`
- [x] Celery task `analysis.run_analysis`
- [x] Skip re-analysis when `(project_id, commit_sha)` already has a ready KB

### Phase C — Composition workflow ✅ (complete — see PROGRESS.md)
- [x] `app/workflows/composition_workflow.py` + `CompositionState` seeded from a KB
- [x] `planner` reads KB modules/entities; validates `key_files` against the KB
- [x] `strategy` reads KB narratives
- [x] `app/knowledge/retrieval.py` — `SectionContextBuilder` (token-bounded)
- [x] Rewrite `writer` as retrieve-then-write; per-section ReAct removed
- [x] Bounded escape hatch (`NEED_CONTEXT:` marker, one retry)
- [x] Parallelise sections within a doc; full outline passed instead of `written_titles`
- [x] Celery task `composition.run_composition`
- [x] `diagram`/`qa`/`formatter`/`publisher` reused unchanged

### Phase D — API and UI ✅ (complete — see PROGRESS.md)
- [x] `POST /api/v1/projects/{id}/analyze` → analysis job
- [x] `GET  /api/v1/projects/{id}/knowledge-base` → status, stats, **suggested doc types**
- [x] `POST /api/v1/projects/{id}/compose` → composition job
- [x] Legacy `POST /projects/{id}/jobs` kept working for API clients; removed from the UI
- [x] UI: project detail shows KB state — *Not analysed* → *Analysing* → *Ready/Degraded*
- [x] UI: doc-type picker unlocked only when KB is usable, suggestions from real evidence
- [x] UI: "Re-analyse" action
- [x] Beyond plan: Card/Badge primitives, durations throughout, phase-aware pipeline panel

### Phase E — Performance and cleanup
- [x] Point `LLM_FAST_MODEL` at a genuinely smaller model — done 2026-08-04 with
      `liquid/lfm2.5-1.2b`; module summaries 445s → 7.8s. Note `plan` had to move to the
      quality tier: on the small model it emitted zero `key_files` and generic sections
- [ ] Make `diagram` opt-in per doc type (64s, 15% of run 18)
- [ ] Decide Neo4j: fold the useful edges into `kb_entities` and drop the service, or
      start querying it. It is currently built every run and queried zero times
- [ ] Human-review gate is a dead end — `_route_after_review` returns `END` with no
      checkpointer, so approval cannot resume. Use a LangGraph interrupt
- [ ] Delete `react_mixin` usage from the writer path once Phase C lands

## Open decisions

1. ~~**Module granularity**~~ — **settled in Phase B**: per-package, decided by
   `LanguageProvider.module_ref_for`. On this repo that gave 29 modules from 146 files, and
   the resulting summaries read well. Revisit only if a language needs different grouping.
2. **KB versioning** — keep N generations per project or only the latest? Proposal: keep
   the latest ready KB plus the one currently being built.
3. **Partial analysis** — should a failed `module_summarizer` block the KB? Proposal: no,
   mark the KB `degraded` and let composition proceed with a warning.
4. **Do narratives belong in the KB or in composition?** Proposal: KB, because they are
   doc-type-independent and expensive.

## Non-goals

- Changing the LLM provider or the offline/LM Studio constraint
- Reworking output formatters
- Incremental/partial re-analysis of a changed subset of files (future work; the
  commit-keyed KB is the prerequisite)
