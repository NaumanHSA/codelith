# Codelith — where the work stands

*Snapshot: 31 August 2026, `e8bd29f`. Update the numbers when they stop being true.*

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
| Commits | 107 |
| Python | 245 files, ~31,900 lines |
| Studio (TS/TSX) | 66 files, ~12,400 lines |
| Tests | 51 files — **804 unit passing, 1 skipped**; 166 integration collected (needs Docker) |
| Migrations | 12 |
| HTTP routes | 48 |
| Apps on `main` | 2 — Quality is built but parked on `feat/qa` |
| Languages analysed | Python, TypeScript, Go, Java |
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
- **Cancellation** — Redis-backed tokens. Long work stays killable; `JobCancelled` is never
  swallowed by a broad `except` and never retried.
- **Six KB tools** — `search_code`, `read_file`, `find_callers`, `find_dependents`,
  `blast_radius`, `list_facts`. Used by Ask, and exposed over MCP.

### The apps

| App | Reads | State |
|---|---|---|
| **Documentation** | retrieval · narratives · entities | Built, on `main`. Markdown / DOCX / MkDocs / Docusaurus. Document types are offered from what the code contains, so a repo with no HTTP routes is never offered an API reference. |
| **Ask the code** | retrieval · code graph · entities | Built, on `main`. Threaded conversations, persisted, exportable. Citations checked. |
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

`codelith/mcp/` adds nothing of its own. It is a **second transport** over
`codelith/knowledge/tools.py`, so Claude Code and Cursor can query the knowledge base
directly. Same tools, plus `list_codebases` to pick one.

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
- **Almost every measurement came from one repository.** `neurosurfer`, 257 Python files.
  Every false positive fixed so far was found by running against real code, which is
  reason to believe a second codebase will find more.
- **Ruff is not wired into Codelith's own CI.** The app runs it on other people's code
  while ours is unchecked. Blocked on SQLAlchemy `Mapped["Project"]` forward references
  producing F821 false positives — needs a per-rule exclusion, not a skip.
- **The legacy single-shot pipeline is still alive.** `documentation_workflow.py` (now
  under the documentation app) backs `POST /projects/{id}/jobs`. New work goes in the
  two-phase graphs; this exists so an old endpoint keeps working.
- **Two Quality bugs shipped output that looked like a pass** before being caught — a mypy
  exit-2 read as success, and a dict-ordering bug that hid a 33:1 layering violation. That
  is precisely the failure the app exists to prevent in others' code, which is the argument
  for running it against something new before trusting it.
- **Integration tests need Docker infra up.** They are not part of a quick loop.
- **Local model dependence.** Grounding and citation behaviour was tuned against
  `qwen/qwen3.5-9b` through LM Studio. Behaviour on a different quality-tier model is
  untested.

## Running it

```bash
cp .env.example .env       # fill in values
make dev                   # Docker infra + hot-reload API on :8000
make migrate               # apply migrations
make worker                # Celery worker, another terminal

cd ui && pnpm install && pnpm dev      # studio on :5173 — needs Node >= 20.19
```

```bash
make test                  # everything
pytest tests/unit/         # fast loop
pytest tests/integration/  # needs Docker
```

## Where the plans live

`.dev/` holds three documents now. The phase plans that built the product were deleted
once complete — keeping a finished plan next to a living one makes the reader guess which
is which, and the git history is the better record of how something was built.

| File | What it is |
|---|---|
| `STATUS.md` | This file. What exists, what is weak, what is open |
| `QA_AGENT_PLAN.md` | Quality, Q0–Q8, plus what was deliberately left out. Kept because the app returns from `feat/qa` and this is the contract it returns to |
| `ASK_SCORECARD.md` | Twenty questions hand-scored against `neurosurfer`. Kept because it is measurement, not a plan — it cost a manual pass and cannot be cheaply regenerated |

Deleted 31 August 2026, all complete: `PLAN.md` / `PROGRESS.md` (analyse/compose
rearchitecture, A–D), `SITE_PLAN.md` (S1–S6), `UX_PLAN.md` / `UX_PROGRESS.md` (U1–U7),
`COMPOSITION_PLAN.md` (C1–C5), `SUBSTRATE_PLAN.md` (K1–K4), `ASK_PLAN.md` /
`ASK_PROGRESS.md` (Q1–Q8), `CODELITH_PLAN.md` / `CODELITH_PROGRESS.md` (C0–C4, including
the GitHub rename), `HANDOFF.md`, `HOME_DESIGN_BRIEF.md`, and `handover/`.

## What is open right now

Verified against the code on 31 August 2026, not carried over from a checkbox.

1. **`diagram` runs on every composition.** `graph.add_edge("linker", "diagram")` is
   unconditional in `composition_workflow.py`. Measured at 64s, ~15% of a run. Should be
   opt-in per doc type. Was E2.
2. **Ruff is not in CI, and CI would fail if enabled.** `.github/workflows/ci.yml` is
   `workflow_dispatch`-only and still lints `app/`, a path that has not existed since the
   rename to `codelith/`. The tree has 375 findings, 201 auto-fixable; only 10 are the
   SQLAlchemy `Mapped["Project"]` F821 false positives, all under `codelith/models/`, so
   one per-directory ignore clears the blocker that was thought to be the whole problem.
3. **The MCP server is pinned below 2.0, not ported.** See *Where it is weak*.
4. **Quality returns from `feat/qa`** once Documentation and Ask settle.
5. **Run Quality against a repository that is not `neurosurfer`.** Blocked on 4.

Settled since the last snapshot, recorded so it is not re-opened:

- **Neo4j is queried now.** The old E3 asked whether to fold the graph into `kb_entities`
  and drop the service, on the grounds that it was built every run and queried never. Ask
  resolved it the other way: `knowledge/questions.py::_add_graph`, `knowledge/grounding.py`
  and the documentation `diagram` agent all query it, and it backs `find_callers`,
  `find_dependents` and `blast_radius`.
- **`react_mixin` is out of the writer path.** Composition uses `CompositionWriterAgent`.
  `ReActMixin` survives only in `agents/writer.py`, reachable solely from the legacy
  single-shot pipeline, which is kept alive on purpose.
- **The Home page redesign shipped** on 10 August in `0971302`.
- **The review gate works** as of 31 August. See *The review gate* below.
- **The GitHub repository was renamed** to `codelith`.

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
