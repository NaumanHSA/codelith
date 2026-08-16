# Codelith — where the work stands

*Snapshot: 16 August 2026, `6b23486`. Update the numbers when they stop being true.*

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
| Tests | 51 files — **799 unit passing, 2 skipped, 4 failing**; 166 integration collected (needs Docker) |
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

- **Four unit tests fail against the installed MCP SDK.** `tests/unit/test_mcp_server.py`
  reads `Tool.inputSchema`; the SDK renamed it to `input_schema`. The server itself is
  unaffected — the tests assert on the SDK's own model, not on our behaviour — but a red
  suite trains people to ignore a red suite, so this should be fixed rather than tolerated.
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

`.dev/` holds plans and progress logs. The ones that still matter:

| File | What it is |
|---|---|
| `CODELITH_PLAN.md` / `CODELITH_PROGRESS.md` | The restructure: rename, apps split, project-as-hub |
| `QA_AGENT_PLAN.md` | Quality, Q0–Q8, plus what was deliberately left out |
| `ASK_PLAN.md` / `ASK_PROGRESS.md` / `ASK_SCORECARD.md` | Ask the code, including hand-scored answers |
| `COMPOSITION_PLAN.md` / `SITE_PLAN.md` | The documentation pipeline |
| `SUBSTRATE_PLAN.md` | The two-phase split |
| `UX_PLAN.md` / `UX_PROGRESS.md` | The studio rebuild |
| `HOME_DESIGN_BRIEF.md` | Open — brief for redesigning Home |

## What is open right now

1. **Home page redesign** — brief written, out with a design specialist. Rename
   Dashboard → Home, richer analysis display, resolve the duplicated app cards.
2. **Wire ruff into CI** — see *Where it is weak*.
3. **Run Quality against a repository that is not neurosurfer.**
