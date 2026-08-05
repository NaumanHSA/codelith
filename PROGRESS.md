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

## Known Issues / Next Up

> **Do these two first.** Everything found while reading runs 1 and 2 traces back to one
> of them:
>
> 1. **Role classification** (`infer_role()`) — 23 of 45 modules land on `unknown`,
>    including the largest. Roles gate narrative topic selection, the planner's module
>    inventory *and* the planner's own `key_files` validation, so a misclassified module
>    is invisible three times over. Details under *Architecture map / role inference*.
> 2. **Strategy inputs** — the stage that sets a document's audience, tone and diagram
>    decision reads two hardcoded narratives truncated to 1,500 chars, and for an API
>    document that meant it never saw a single endpoint. Details under *Narrative
>    delivery*.

- **PDF** — no formatter exists; `/documents/{id}/export` advertises it and raises
- **Standalone export** only implements Markdown; DOCX/MkDocs/Docusaurus work through a
  generation job's `output_formats` but not through the export endpoint
- **Neo4j** is populated but never queried — fold the useful edges into `kb_entities` or
  drop the service (Phase E3)
- **Human-review gate** returns `END` with no checkpointer, so approval cannot resume the
  graph; needs a LangGraph interrupt (Phase E4)
- **`diagram`** should be opt-in per doc type — 15% of run 18 (Phase E2)
- **Languages** — only Python has a provider; other files are indexed for retrieval but
  contribute no extracted symbols
- **Chunking is naive and worth redoing.** `chunk_files()` cuts fixed 40-line windows
  with a 5-line stride overlap, then truncates each to 1500 chars. Two consequences,
  both measured on run 1 of this repo (1,103 chunks / 255 files):
  - It is **not syntax-aware**, so a chunk routinely starts mid-function and ends
    mid-docstring. The language provider has already extracted every symbol with its
    line span — the chunker ignores that and re-derives nothing from it.
  - **34% of chunks (378) hit the 1500-char cap**, and their line metadata then lies:
    they claim a 40-line span but hold ~36 lines of text. The 5-line overlap usually
    recovers the dropped tail, but only when truncation falls past line 35 — a file
    with long lines leaves a band of source in no chunk at all, while
    `SectionContextBuilder._format()` still labels the block `path:start-end` as if
    it were complete.

  A better approach is to chunk on symbol boundaries from `LanguageProvider` (one
  function/class per chunk, splitting only what exceeds the budget), fall back to line
  windows for files no provider claims, and make the char cap a function of the window
  rather than an independent constant. Deliberately **not implemented yet** — noted
  while reading run 1's artifacts.

### Architecture map / role inference — from run 1 (neurosurfer, 45 modules)

Read off `runs/1/artifacts/08_architecture_synthesizer.architecture_map.json`. The
synthesis itself is sound — all 9 frameworks and dependencies it named verify against
the extracted dependency list, so the grounding instruction is working. The problems
are upstream of it, and none is implemented yet.

- **`infer_role()` fails on half the codebase, and on the largest half.** 23 of 45
  modules come out `role = unknown`, totalling **13,770 LOC — more than every other
  role combined** (`neurosurfer/graph/engine` at 2,417 LOC among them). Roles are not
  cosmetic: `_ROLE_TRIGGERS` picks which narratives get written, `_ROLE_FOCUS` picks
  which modules the planner sees per doc type, and the deterministic fallback map
  groups by role. An `unknown` module is invisible to all three. Highest-value fix
  here. See `app/knowledge/roles.py`.
- **Entrypoint detection is too loose.** All 10 extracted entrypoints were echoed into
  the map, including `tests/test_mcp_client.py`, `scripts/gen_button_svgs.py`,
  `scripts/svg_to_png.py` and two `tutorials/capstone/*` files. Almost certainly a bare
  `if __name__ == "__main__"` test in `PythonProvider.detect_entities`. The fix belongs
  behind the language seam, and it matters because `entry_points` feeds the diagram
  prompt directly.
- **The map has no edges.** It describes services and layers but nothing about which
  service calls, imports or depends on which — so `DiagramAgent` has to invent every
  arrow it draws. A `relations: [{from, to, kind}]` field would close it, and the
  import graph is *already* computed every run and left unqueried in Neo4j. This and
  the E3 Neo4j decision are the same piece of work.
- **The map is never persisted** — produced in analysis, consumed by
  `narrative_writer`, then discarded. It is not a column on `kb`, not in `stats_json`,
  not an entity. `CompositionState` has no `architecture_map` key, so
  `DiagramAgent`'s `state.get("architecture_map", {})` is **always empty** in the
  two-phase path: every diagram is drawn from "(no services identified)", entrypoints
  "main", patterns "none identified", plus a 1,000-char excerpt of the document text.
  Also why nothing has ever pushed back on the map's shape. Pairs with E2.
  - Minor, but decide it when persisting: the map keys modules by dotted `name`
    (`neurosurfer.agents.runtime`) while `kb_modules.path` uses slashes
    (`neurosurfer/rag`). `name` is the join key.

### Narrative topics — widen the vocabulary, then let the model select

Agreed design, **not implemented**. Today `_select_topics()` picks topics with hardcoded
heuristics: two always-on, role triggers, entity-kind triggers, and substring matching on
module names. It under-fires — run 1 produced 6 of 10 topics, and the misses were caused
by our own heuristics rather than by absent evidence.

The plan, in order:

1. **Expand `NarrativeTopic` so it spans project shapes, not just web backends.** Today's
   10 assume a request/response service. Candidates to cover CLIs, libraries, frontends
   and pipelines: `concurrency`, `extensibility` (plugin/registry systems), `cli_usage`,
   `observability`, `build_and_release`, `state_management`, `performance`. Each addition
   needs its own `TOPIC_GUIDANCE` entry *and* a slot in the doc-type mapping, or it will
   be written and never read.
2. **Replace heuristic selection with one fast-tier LLM call.** Give it the architecture
   map, role/entity counts and module summaries; get back the subset of enum topics the
   evidence supports, with a confidence and a one-line reason. Same shape as
   `suggest_doc_types()`, which is already an established pattern here. Cheaper than the
   status quo, which pays *quality-tier* write calls for topics the model then declines
   via `NOT_APPLICABLE`.
3. **Keep deterministic triggers as a floor, not the decision.** 24 env vars should force
   `configuration` in whether or not the selector names it. A bad selection call must
   degrade quality, never silently drop a topic the facts plainly justify.
4. **Keep `NOT_APPLICABLE`** as the final backstop.

**Hard constraint — the vocabulary stays closed.** `topic` is a lookup key, not a label:
`SectionContextBuilder._narratives_for()` fetches exact topics per doc type
(`api` → `request_lifecycle` + `auth`), `kb_narratives.topic` is an indexed `String(48)`,
and `topics_present()` feeds the KB stats. Free-form topics from the model would make an
API document ask for `auth`, find nothing, and write the section without it — with no
error anywhere. The model chooses *from* the enum; it does not invent members of it.

Two bugs to fix in the same pass:

- **`error_handling` is unreachable.** It is in the enum and has `TOPIC_GUIDANCE` prose
  written for it, but appears in `_ALWAYS`, `_ROLE_TRIGGERS`, `_ENTITY_TRIGGERS` and the
  auth-hint path zero times. No codebase can trigger it.
- **`auth` is selected by substring-matching module names** against
  `("auth", "security", "permission", "rbac", "identity", "login", "token")` — it misses
  any project that names its module something else, and fires on anything containing
  "token".

### Narrative delivery — who gets which narrative, and how much of it

Found by reading run 2 (composition of an **api** document for neurosurfer). Not
implemented. The strategy call is where a document's audience, tone and diagram decision
are set, and it was making that call nearly blind to the API.

Measured on `runs/2/artifacts/02_strategy.prompt.json` — the whole prompt for an *API*
document contained:

```
'fastapi' -> 0    'endpoint' -> 0    '/v1' -> 0
'FastAPI' -> 1    'route'    -> 2    'http' -> 0
```

One passing mention of "a FastAPI gateway", plus `{"route": 4}` in the fact counts. The
actual endpoint list — `GET /`, `GET /health`, `GET /v1/models`,
`POST /v1/chat/completions` — was sitting in `request_lifecycle.md` and was never passed.

- **Select narratives by requested doc type, not by hardcode.** `strategy.py` fetches
  `OVERVIEW` and `ARCHITECTURE` literally, regardless of what was asked for; the planner
  takes `OVERVIEW` only. `SectionContextBuilder._narratives_for(doc_type)` already does
  the right thing (`api` → `request_lifecycle` + `auth`, `deployment` → `deployment` +
  `configuration`). Lift that mapping into a shared helper and have all three consumers
  use it. This is removing an inconsistency, not inventing a mechanism.
- **Replace the flat `[:1500]` with a per-consumer budget.** The architecture narrative
  is 5,147 chars, so strategy saw **29% of it**, cut mid-word at ``\`OtelExporter\` and ` ``.
  All six narratives in full are 18,379 chars ≈ 4,600 tokens — for **one call per
  composition job**, the cap buys nothing. Strategy and planner can take full text.
  Section context is the one place the budget is genuinely contested
  (`COMPOSITION_SECTION_TOKEN_BUDGET`), and there `_trim()` drops narratives *third*,
  after retrieved chunks and after source blocks are cut to one — so it should trim by
  relevance rather than by "pop the last one".
- **Narratives should get denser, not longer.** The goal is information per character:
  concrete paths, symbol names, endpoints and counts instead of padded prose. A narrative
  is written once per commit and then read by every strategy call, every plan and every
  section, so density is what compounds — length just crowds out source at write time.
  The prompt already forbids speculation; it should also push for specifics over
  sentences.
- **`REACT_CONTEXT_WINDOW_LIMIT` is tighter than the code intends.** `_call_llm()` runs
  `trim_to_limit(messages, REACT_CONTEXT_WINDOW_LIMIT)` on *every* call. `config.py`
  defaults it to 14000 ("single-shot `_call_llm` trim target"); `.env.example` sets 6000,
  which is what this machine inherited. That global ceiling sits just above the ~4,600
  tokens full narratives would need, so raise it to 14000 **before** uncapping anything,
  or the trim will silently eat the front of the message instead.

### Section context is under-filled — supply-side, not budget-side

From run 2's `13_writer.api.context_stats.json`. Not implemented. The instinct that
sections are "written from too little" is correct, and the budget is not the reason:

| section | tokens | of 6000 | module summaries | narratives | source blocks |
|---|---|---|---|---|---|
| Introduction and Entry Points | 1930 | 32% | 1 | 1 | 1 |
| HTTP Endpoints and Routes | 3010 | 50% | 1 | 1 | 4 |
| Agent Execution Logic | 5394 | 90% | 2 | 1 | 10 |

`_trim()` barely ran. Sections are starved, not clipped — the first one left **68% of its
budget unspent**. Four causes:

- **`_validate()` drops real KB paths.** It checks `key_files` against the union of
  `files_json` for the modules *shown to the planner* — which are role-filtered — rather
  than against the whole KB. The planner asked for three files for section 1
  (`neurosurfer/__main__.py`, `app/cli/app.py`, `app/server/api/router.py`); the first two
  belong to modules with roles `unknown` and `cli`, outside `_ROLE_FOCUS["api"]`, so they
  were discarded as hallucinations. **They exist in the KB.** The section went from three
  anchor files to one — 15 lines of verbatim source — and the dropped files then showed up
  anyway as 40-line chunks in the semantic-search overflow. Validate against the full KB
  file set; keep the role filter for what the *prompt* shows.
- **Module summaries are scoped to key-file owners only.** `find_for_files(key_files)`
  then `[:6]`, so 1–3 key files yield 1–2 summaries out of 44 in the KB. The cheapest,
  densest context we own is almost entirely unused.
- **Only one narrative reaches any section.** `api` maps to `request_lifecycle` + `auth`,
  and `auth` was never written — so *"Security and Permissions"* was written with no auth
  narrative at all. Straight consequence of the topic-selection issue above.
- **Retrieval is a fixed 6 blocks** regardless of how much budget is left. It should fill
  toward the budget, not to a constant.

### Diagrams are fixed, ungrounded, unvalidated and — for most doc types — discarded

Run 2 evidence. Not implemented. `DiagramAgent` always makes exactly two calls with
hardcoded names, `Architecture Overview` (graph) and `Request Flow` (sequence), whatever
the doc type, the plan or the document says. Four compounding failures:

1. **Ungrounded.** Composition never populates `architecture_map`, so the prompts got
   `"(no services identified)"`, entrypoints `"main"`, patterns `"none identified"`,
   deps `"none"`, and `{}` for the map. See the architecture-map persistence item.
2. **So the model invented a system.** `21_diagram.Architecture-Overview.mmd` draws
   `Workers`, `Storage`, `Data Ingestion`, `Update Model`, `Validation Layer`,
   `Query Service`, `Feedback Loop` — **none of which exist in neurosurfer**. The real
   services (agents, tools, llm, graph, mcp, tracing) appear nowhere.
3. **Neither output is valid Mermaid.** One ends in `style graph { node fill #4a4a4a }`;
   the other opens with the literal text `mermaid diagram:` and uses `--async->`,
   `--style thick` and an ASCII `|-->` tree. `_clean_mermaid()` strips code fences and
   nothing else — there is no syntax validation at any point.
4. **Then they were discarded.** `_inject_diagrams()` fires only when
   `doc_type == "architecture"`, so the published API document contains zero mermaid
   blocks. Two LLM calls, wasted silently.

Target design:

- **Derive the diagram set from the written document**, not from a constant. Decide what
  is worth drawing (possibly nothing) from the doc type, the section plan and the
  finished markdown: an API document wants a request sequence over its *real* routes; a
  data-model document wants an ER diagram; an architecture document wants a component
  graph. Name each diagram from what it depicts.
- **Ground every node in KB facts** — the persisted architecture map (with the `relations`
  edges noted above), routes, entrypoints and module names — and where that is too thin,
  retrieve over `code_chunks` for the specific thing being drawn, the same
  retrieve-then-write discipline the writer already uses. A node whose label is not a real
  symbol, module or route should not be drawable.
- **Validate before accepting.** Parse the Mermaid, retry once on failure, drop the
  diagram if it still will not render. Never publish output that cannot be rendered.
- **Inject into the document it was generated for**, not only `architecture`.

Subsumes E2 (`diagram` opt-in per doc type): once the set is derived, "no diagram
warranted" becomes an ordinary outcome rather than a config flag.

### Narrative topics — widen the vocabulary, then let the model select

Agreed design, **not implemented**. Today `_select_topics()` picks topics with hardcoded
heuristics: two always-on, role triggers, entity-kind triggers, and substring matching on
module names. It under-fires — run 1 produced 6 of 10 topics, and the misses were caused
by our own heuristics rather than by absent evidence.

The plan, in order:

1. **Expand `NarrativeTopic` so it spans project shapes, not just web backends.** Today's
   10 assume a request/response service. Candidates to cover CLIs, libraries, frontends
   and pipelines: `concurrency`, `extensibility` (plugin/registry systems), `cli_usage`,
   `observability`, `build_and_release`, `state_management`, `performance`. Each addition
   needs its own `TOPIC_GUIDANCE` entry *and* a slot in the doc-type mapping, or it will
   be written and never read.
2. **Replace heuristic selection with one fast-tier LLM call.** Give it the architecture
   map, role/entity counts and module summaries; get back the subset of enum topics the
   evidence supports, with a confidence and a one-line reason. Same shape as
   `suggest_doc_types()`, which is already an established pattern here. Cheaper than the
   status quo, which pays *quality-tier* write calls for topics the model then declines
   via `NOT_APPLICABLE`.
3. **Keep deterministic triggers as a floor, not the decision.** 24 env vars should force
   `configuration` in whether or not the selector names it. A bad selection call must
   degrade quality, never silently drop a topic the facts plainly justify.
4. **Keep `NOT_APPLICABLE`** as the final backstop.

**Hard constraint — the vocabulary stays closed.** `topic` is a lookup key, not a label:
`SectionContextBuilder._narratives_for()` fetches exact topics per doc type
(`api` → `request_lifecycle` + `auth`), `kb_narratives.topic` is an indexed `String(48)`,
and `topics_present()` feeds the KB stats. Free-form topics from the model would make an
API document ask for `auth`, find nothing, and write the section without it — with no
error anywhere. The model chooses *from* the enum; it does not invent members of it.

Two bugs to fix in the same pass:

- **`error_handling` is unreachable.** It is in the enum and has `TOPIC_GUIDANCE` prose
  written for it, but appears in `_ALWAYS`, `_ROLE_TRIGGERS`, `_ENTITY_TRIGGERS` and the
  auth-hint path zero times. No codebase can trigger it.
- **`auth` is selected by substring-matching module names** against
  `("auth", "security", "permission", "rbac", "identity", "login", "token")` — it misses
  any project that names the module something else, and fires on anything containing
  "token".
- **Legacy pipeline** — `documentation_workflow.py` and the agents it owns
  (`coordinator`, `code_understanding`, `react_mixin`) exist only for the old
  `POST /projects/{id}/jobs` endpoint

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
