# Codelith — where the work stands

*Snapshot: 8 September 2026, on `main` after the open-source release work. Update the
numbers when they stop being true.*

**This is the planning document.** The phase plans that built the product (analyse/compose,
the site, the UX overhaul, the substrate, Ask, the Codelith rename) all completed and were
deleted on 31 August 2026 — their record is the git history and the code itself. What
survived them is here, in `QA_AGENT_PLAN.md`, and in `ASK_SCORECARD.md`.

---

## What this is

Codelith reads a codebase once and turns it into a **knowledge base**. Everything else is
an app that consumes it.

> **Analysis is the product; apps are what it unlocks.**

That sentence is load-bearing. The repository was built documentation-first and named for
it, so code written under the old premise couples analysis to documents. Undoing that
coupling has been the main structural work of the last two months, and it is mostly — not
entirely — done.

Everything runs on the operator's own machine. No code, no question, and no package name
leaves the box. That claim has design consequences everywhere, and it has already vetoed
features (see *Deliberately not built*).

## Snapshot

| | |
|---|---|
| First commit | 8 June 2026 |
| Commits | 217 |
| Python | 283 files |
| Studio (TS/TSX) | 84 files |
| Tests | 78 files — **1301 unit passing, 2 skipped**; **204 integration passing**. The whole suite runs in **under a minute against a temporary SQLite file** and starts nothing |
| Migrations | **5** — fourteen were squashed to one baseline when the second database went; four have landed since |
| HTTP routes | 90 (82 under `/api/v1`) |
| Apps on `main` | 3 — Quality is built but parked on `feat/qa` |
| Services to run | **none.** One SQLite file under `~/.codelith` |
| Ways to run it | `make dev` for two dev servers, or `make docker` for one container serving both on `:8000` |
| Lint | **ruff clean** across `codelith/`, `tests/` and `alembic/`, enforced in CI |
| Languages analysed | Python, JavaScript, TypeScript, Go, Java |
| Languages checked by Quality | Python only (on `feat/qa`) |

## The shape

Three phases, and the split drives most of the design.

1. **Analyse** — `codelith/workflows/analysis_workflow.py`. Builds a knowledge base from a
   repository, once per commit SHA. **Takes no document type, and must never take one.**
   Eight agents: `repo_analyzer → structured_extractor → module_summarizer →
   graph_builder → semantic_indexer → architecture_synthesizer → narrative_writer →
   site_planner → kb_persister`.
2. **Compose** — the documentation app. Writes requested documents from the stored KB,
   retrieve-then-write per section. **Never re-reads the repository.**
3. **Ask** — the second app on the same KB. It proved the pattern by needing nothing from
   the documentation pipeline at all.

**An app is defined by what it reads from the knowledge base**, and optionally by what it
derives for itself. Adding one should mean one entry in `codelith/apps/registry.py` and one
page — never a change to analysis. If you find yourself editing an analysis agent to add an
app, stop: the app is asking for something the KB should hold for everyone.

## What is built

### The base

- **Knowledge base** — modules, entities, code graph, narratives, semantic index. For a
  257-file Python repo that comes to 45 modules, 143 entities, 3,244 symbols, 2,525 calls,
  745 imports, 1,692 indexed chunks, 12 narrative topics.
- **Language abstraction** — `codelith/languages/`. Four providers. No language-specific
  code exists outside this package; agents and the KB speak a neutral taxonomy. Adding a
  language means adding one provider, not touching agents or schema.
- **Retrieval + grounding** — every citation is checked against the evidence actually
  retrieved. One that does not resolve is stripped rather than shown.
- **Cancellation** — an in-process flag store behind `core/cancellation.py`. Long work stays
  killable; `JobCancelled` is never swallowed by a broad `except` and never retried.
- **Six KB tools** — `search_code`, `read_file`, `find_callers`, `find_dependents`,
  `blast_radius`, `list_facts`. Used by Ask, and exposed over MCP.
- **Pre-flight** — `codelith/knowledge/preflight.py`. Given a path or a symbol it assembles
  what an edit would touch: importers, transitive reach with distance, call sites, whether a
  test reaches it, the routes and env vars the file declares, and the written pages that
  cite it. Four indexed queries, no model call. Exposed as the `before_edit` MCP tool and at
  `GET /projects/{id}/preflight`. `reach_weight` lives here and is the ranking every caller
  should sort on — reach capped at 40, a written page worth five importers. It was Quality's
  and it is in the base so that ranking by reach does not require that app.
- **The code graph in SQL** — six tables and one recursive CTE, in the same database as
  everything else. It answers the three questions the graph exists for; nothing to run.

### The apps

| App | Reads | State |
|---|---|---|
| **Documentation** | retrieval · narratives · entities | Built, on `main`. Markdown / DOCX / MkDocs / Docusaurus. Document types are offered from what the code contains, so a repo with no HTTP routes is never offered an API reference. |
| **Ask the code** | retrieval · code graph · entities | Built, on `main`. Threaded conversations, persisted, exportable. Citations checked. |
| **What changed** | modules · entities · written pages | Built, on `main`. Compares two readings of one repository — modules added, removed or rewritten, routes that came and went, and **which written pages now describe code that moved**. Needs the codebase analysed at two commits; `uq_kb_project_commit` means a re-run on the same commit upserts rather than creating a second reading, so the API says `comparable: false` rather than showing an empty diff. |
| **Quality** | code graph · entities · modules | Built (Q0–Q8, Aug 2026), then **parked on `feat/qa`**. Findings from ruff and mypy **ranked by what each one touches**; surface with no test; offline dependency audit; layering rules derived from the codebase itself. |

**Why Quality is parked.** It is the youngest of the three and it matured against two
neighbours still changing shape. An app held to a moving contract is an app rebuilt
twice, so it waits until Documentation and Ask settle. It comes back from that branch
whole, not re-added piecemeal. Nothing migrated on the way out — it owned no tables.

Quality was the first app with **two stages**: `codelith/apps/qa/deep.py` parses the
checkout for per-file symbol spans, because the KB stores symbols per module and records
only where they start. Derived data stays inside the app — a project that never opens an
app never pays for it. That is still the pattern for any future app that needs more than
the KB holds.

### Not an app

`codelith/mcp/` adds nothing of its own. It is a **second transport** over the base, so
Claude Code and Cursor can query the knowledge base directly. Eight tools: the six from
`knowledge/tools.py`, `list_codebases` to pick one, and `before_edit` from
`knowledge/preflight.py`.

`before_edit` is the one that changes what this is for. The others answer questions about
a codebase; that one is called *before* changing it, and it is the reason an agent connects
at all. It is deliberately **not** in `TOOL_SCHEMAS` — those six are what an answering model
reaches for mid-question, and handing a pre-flight to a model with no edit to make is a
tool it picks at random.

### The studio

React 19 + Vite 8 + Tailwind 4 in `ui/`. Light theme, orange accent, blueprint/terminal
character. Colours come from tokens (`--paper`, `--ink`, `--hot`, `--rule`, `--sunk`,
`--panel`) — never a raw Tailwind colour. Nothing loads from a CDN; fonts are bundled.

## The rules, and how they hold

These are enforced by tests, not by convention or review.

- **`tests/unit/test_module_isolation.py`** fails if the base imports an app, or if one app
  imports another. Known exceptions live in `KNOWN_LEAKS` **with a written reason**, and a
  second test fails when an entry stops being true — so the list can only shrink.
  One entry today: `agents/analysis/site_planner.py`, because analysis plans the
  documentation site while it has the codebase open. The real fix is a behaviour change,
  not a refactor, so it is recorded rather than hidden.
- **No language-specific code outside `codelith/languages/`.**
- **All DB access through `codelith/db/repositories/`.** Routes are thin.
- **All LLM calls through `codelith.llm.client`**, with the endpoint resolved by
  `codelith.llm.router.select_spec(task_type)`. Model tier is picked by task type, never by
  the caller.
- **A concurrent phase must not share one `AsyncSession`.**

## Deliberately not built

Recorded so that nine green ticks in a plan don't read as "everything got built". Each has
a section in `.dev/QA_AGENT_PLAN.md` saying what it would take. The Quality rows describe
gaps in the app as it stands on `feat/qa`; they are what it comes back to, not work
outstanding on `main`.

| | Why |
|---|---|
| **Test execution** | Quality writes tests and runs none. Needs a sandbox and a product decision about executing generated code inside someone's checkout. |
| **Dismissal state** | Needs a table, a migration, and an answer to: *does dismissing a finding survive a re-analysis that moves the line number?* Not a checkbox. |
| **Latest-version dependency checks** | Would send every package name to a third party. Vetoed by the offline claim. |
| **Checkout pinned to the analysed SHA** | Ingesters take a branch, not a revision. Reported via `drift_note` rather than hidden. |
| **Quality for non-Python languages** | One entry in `TOOLS_BY_LANGUAGE`. A Go repo is checked by nothing today — and *says so* rather than reading as clean. |
| **Dark theme** | Tokens are structured for it; components have not been checked against it. |

## Where it is weak

Honest list. Nothing here is a crisis; all of it is worth knowing before trusting a number.

- **The MCP server is held at `mcp<2` by a pin, not by a port.** 2.0 dropped the
  `@server.list_tools()` / `@server.call_tool()` decorators `codelith/mcp/server.py` is
  written against; its `Server` is handler-registration only. `>=1.0.0` let a resolver
  take that upgrade on our behalf and broke four tests. Pinned for now — the port is real
  work and should be chosen, not stumbled into.
- **Nearly every measurement came from one repository.** `neurosurfer`, 257 Python
  files. `enigma` has since been analysed end to end, which is a second data point and
  not yet a second opinion — every false positive fixed so far was found by running
  against real code, so a third codebase will find more.
- **Nobody can install this — still, but for a much smaller reason.** The six containers
  are gone, the `.env` is optional, and the CLI the landing page advertised now exists.
  What is left is that the package has never been published, so `pipx install codelith`
  does not resolve. Everything the roadmap built was aimed at that one command.
- **Line length is the one lint rule still off.** 143 violations across forty files —
  mostly long call signatures and prose in docstrings. Everything else in `E`, `F`, `I`,
  `UP` and `B` is clean and enforced on every push and pull request. `E501` comes off the
  ignore list once the backlog is burned down; it is excluded so that turning CI on did
  not require a mechanical reformat of the whole tree in the same change.
- **The legacy single-shot pipeline is still alive.** `documentation_workflow.py` (now
  under the documentation app) backs `POST /projects/{id}/jobs`. New work goes in the
  two-phase graphs; this exists so an old endpoint keeps working.
- **Two Quality bugs shipped output that looked like a pass** before being caught — a mypy
  exit-2 read as success, and a dict-ordering bug that hid a 33:1 layering violation. That
  is precisely the failure the app exists to prevent in others' code, which is the argument
  for running it against something new before trusting it.
- **Integration tests are no longer a separate loop.** 184 of them, against a temporary
  SQLite file with every model call faked, and the whole suite finishes in 32 seconds.
  Nothing to provision, in CI or locally.
- **The stage-coverage tests are weaker than they read.** `test_the_ui_knows_every_*_stage`
  claims to catch a stage missing from the studio's progress table; it actually asserts
  that one string appears in `narrate.ts`. A node added to either graph would not be
  caught. Both also read that file with the platform encoding, which meant they could not
  run on Windows at all until 2 September.
- **Local model dependence.** Grounding and citation behaviour was tuned against
  `qwen/qwen3.5-9b` through LM Studio. Behaviour on a different quality-tier model is
  untested.
- **Drift and the pre-flight have not been measured on a large repository.** Both are
  indexed lookups and both are bounded — the blast radius is capped at 200 rows and three
  hops, and the drift report only lists what moved — but "fast on a 42-file SDK" is not a
  number worth quoting.
- **`scripts/` is outside the linted surface.** `make lint` and CI cover `codelith/`,
  `tests/` and `alembic/`; `scripts/test_workflow.py` currently has nine ruff findings that
  nothing fails on. Either bring it in or say why it is exempt.
- **`jobs.celery_task_id` holds `inline-<uuid>`.** The column outlived the thing it was
  named for. Renaming it is a migration plus four call sites — small, but a schema change
  for a naming problem, so it waits for a change that touches the table anyway.

## Running it

Nothing to start. The database is a file under `~/.codelith`, created on first use.

```bash
make dev                   # hot-reload API on :8000
make migrate               # apply migrations

cd ui && pnpm install && pnpm dev      # studio on :5173 — needs Node >= 20.19
```

Or without the studio at all:

```bash
codelith analyse .         # read this repository
codelith ask "how does authentication work?"
codelith mcp               # serve the knowledge base to a coding agent
```

```bash
make test                  # everything, 32 seconds, starts nothing
pytest tests/unit/         # fast loop
pytest tests/integration/  # a temporary SQLite file, no Docker
```

## Where the plans live

`.dev/` holds four documents now. The phase plans that built the product were deleted
once complete — keeping a finished plan next to a living one makes the reader guess which
is which, and the git history is the better record of how something was built.

| File | What it is |
|---|---|
| `STATUS.md` | This file. What exists, what is weak, what is open |
| `QA_AGENT_PLAN.md` | Quality, Q0–Q8, plus what was deliberately left out. Kept because the app returns from `feat/qa` and this is the contract it returns to |
| `ASK_SCORECARD.md` | Twenty questions hand-scored against `neurosurfer`. Kept because it is measurement, not a plan — it cost a manual pass and cannot be cheaply regenerated |
| `ROADMAP.md` | What comes next, in phases: the CLI, solo mode, MCP as the headline, drift, agent pre-flight. The only forward-looking document here — everything else records what happened |

Deleted 31 August 2026, all complete: `PLAN.md` / `PROGRESS.md` (analyse/compose
rearchitecture, A–D), `SITE_PLAN.md` (S1–S6), `UX_PLAN.md` / `UX_PROGRESS.md` (U1–U7),
`COMPOSITION_PLAN.md` (C1–C5), `SUBSTRATE_PLAN.md` (K1–K4), `ASK_PLAN.md` /
`ASK_PROGRESS.md` (Q1–Q8), `CODELITH_PLAN.md` / `CODELITH_PROGRESS.md` (C0–C4, including
the GitHub rename), `HANDOFF.md`, `HOME_DESIGN_BRIEF.md`, and `handover/`.

## What is open right now

**All six phases of `ROADMAP.md` are done** — the CLI, solo mode, the collapse to one
mode, MCP as the headline, drift, and the agent pre-flight. What remains:

1. **`pipx install codelith` still does not resolve.** Every phase above was aimed at that
   command and the package has not been published. It is now the single largest gap between
   what this is and what anybody can try.
2. **The MCP server is pinned below 2.0, not ported.** Blocked on `langchain-mcp-adapters`
   pinning `mcp<2.0.0`, which is not our code. Roadmap Phase 3 records what the port
   actually involves — new packages, schemas derived from signatures rather than data, and
   a second HTTP stack — so nobody rediscovers it.
3. **Quality returns from `feat/qa`** once Documentation and Ask settle. Phase 5 took the
   half that was general — `reach_weight` — into the base without un-parking the app.
4. **Run Quality against a repository that is not `neurosurfer`.** Blocked on 3 —
   though `enigma` has now been analysed end to end, so the *analysis* pipeline is no
   longer measured on a single repository.
5. **Jobs stuck `running` after a hard kill keep their pages claimed.** A process killed
   outright runs no handler. Pages whose job is *terminal* are now released at start, but
   telling "abandoned" from "still running" needs a lease, and guessing wrong kills live
   work.
6. **Duplicate headings collide on their anchor.** Two `## Entry Points` in one page
   produce one id, so both table-of-contents entries jump to the first. Fixing it means
   agreeing a de-duplication rule between `anchorId` in `ui/src/app/lib/site.ts` and
   `anchor_id` in `codelith/knowledge/sites.py`, which the linker also validates against
   — three places that must produce identical strings.

Everything else lives in `ROADMAP.md`, which is where the work goes next.

Settled since the last snapshot, recorded so it is not re-opened:

- **There is one mode, and it needs no services.** PostgreSQL, Redis, Neo4j, MinIO and
  Celery are gone — not made optional, deleted, along with the setting that chose between
  them. `tests/unit/test_storage_seams.py` was inverted to enforce it: it no longer checks
  that each service has one door, it checks that those libraries do not come back.
  Everything runs against one SQLite file under `~/.codelith`.
- **The graph was worth keeping, and did not need a graph database.** The old E3 asked
  whether to fold it into `kb_entities` and drop the service, on the grounds that it was
  built every run and queried never. Ask resolved the first half the other way — it backs
  `find_callers`, `find_dependents`, `blast_radius`, `grounding`, the `diagram` agent, and
  now the pre-flight. Phase 2 resolved the second: two of its three questions are a join
  and the third is a recursive CTE, so it lives in six ordinary tables.
- **The inline worker survives a logger that throws.** `except Exception` wrapped the task
  but the `logger.exception` reporting it sat inside that handler, so a logger that raised
  took the thread with it and every job queued afterwards waited for ever. Found by the
  suite hanging — which is precisely how it would have presented in production, and why the
  guard now covers the logging too.
- **`react_mixin` is out of the writer path.** Composition uses `CompositionWriterAgent`.
  `ReActMixin` survives only in `agents/writer.py`, reachable solely from the legacy
  single-shot pipeline, which is kept alive on purpose.
- **The Home page redesign shipped** on 10 August in `0971302`.
- **The GitHub repository was renamed** to `codelith`.
- **The review gate works.** See below.
- **Compose was merged into the documentation site.** One inventory, not two; format is
  chosen on export rather than before writing.
- **`diagram` was never the 64-second problem it was recorded as.** That measurement
  predates `DIAGRAMS_ENABLED` defaulting to false. Model-written diagrams have been off
  by default for some time; what the stage costs now is a few seconds of graph-derived
  work. The real defect was `include_diagrams`, which sat in `JobConfig` from the
  beginning and was never read by anything — an API that accepted a flag and ignored it.
  It is honoured now.

## The review gate

Built 31 August 2026. Recorded here because it spent months as a decision nothing acted
on, and the shape of that failure is worth keeping.

**What it is for.** Review is **opt-in per job**: `human_review: true` sets
`requires_human_review`. Composition writes the documents, and the `qa` agent scores each
against the source it was written from — `all_approved = all(r["review"]["approved"])`.
The gate fires only when a reviewer asked for review *and* QA did not pass everything, so
it holds the pages that are actually in question rather than every page.

**How it works.** `_route_after_review` sends `await_review` to a `hold` node, which
writes the tail of the graph's state — written pages, diagrams, QA verdicts, the plan —
to `jobs.resume_state_json` and parks the job as `awaiting_review`. The studio shows the
flagged pages with their scores and claim counts.
`POST /projects/{project_id}/compose/{job_id}/approve` then replays **only the tail** —
`formatter` then `publisher` — against the stored pages. Rejecting fails the job and
drops the payload.

**Two decisions worth keeping.**

*No checkpointer.* LangGraph's `interrupt` is the textbook answer and was rejected: the
state holds `project`, `job` and `sandbox` — live objects that do not serialise, and that
should not be frozen anyway, because resuming ought to publish against the project as it
is now rather than as it was. Storing only the serialisable tail and rebuilding the rest
is smaller, survives a worker restart, and needs no new dependency or tables.

*Replay the tail, never the writer.* Re-running composition from the top would publish
text nobody reviewed — the exact outcome the gate exists to prevent, reached through the
feature meant to prevent it. `tests/unit/apps/test_review_gate.py` fails if the tail
graph grows a node beyond `formatter` and `publisher`.

**Where approve lives, and why not in `jobs.py`.** Resuming means dispatching the
documentation feature's Celery task, and `codelith/api/v1/jobs.py` is not a composition
root — `test_module_isolation.py` forbids it naming a feature. The route sits in
`api/v1/projects.py` beside `/compose`, which already owns that wiring. The old
`POST /jobs/{id}/approve` was removed rather than left: it could only set the status to
`running`, which left approved jobs running forever with no worker on them.

**Verified end to end** on 31 August against `neurosurfer`: a held job stored a 171KB
payload, the studio showed the flagged page with `4/4 claims verified · score 3`, and
Approve published page 123 in 0.25s and cleared the payload.

**Where it earns its place.** Documentation that faces outward — an API reference going
to customers, onboarding docs, anything with an accuracy claim attached. For internal
notes, leave it off; the `flagged` chip in the page's provenance is enough.
