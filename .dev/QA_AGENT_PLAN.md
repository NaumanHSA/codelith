# QA Agent — Plan

Captured before building, because the idea as first described is **five products**, and
three of them belong here.

The premise: a feature that does what a testing team does — writes test cases, finds
bugs and dead code, flags bad practice, suggests improvements, watches runtime logs,
and audits dependencies.

---

## The framing that makes it worth building

**Every linter finds the bug. Only Codelith knows what the bug touches.**

Ruff already catches the `F821` that broke composition — it is configured, `F` is
selected in `pyproject.toml`, and nobody ran it. Reimplementing ruff and mypy would be
a worse version of tools that are deterministic, fast, and free.

What no linter can say is the second half:

> `F821` at `app/agents/diagram.py:442` — that method runs inside the composition
> workflow, so this breaks **every documentation job**, and 3 written pages cite the
> file.

The finding is a commodity. The blast radius is not, and the blast radius is the thing
the knowledge base already holds. **Run the existing tools; explain their output
against the KB.** That is the product.

---

## What ships, what does not

| Capability | Verdict | Why |
|---|---|---|
| Run existing tools, explain with impact | **Build first** | The differentiated half. `get_blast_radius` and the entity index already exist |
| Dependency audit — outdated, incompatible | **Build** | `dependency` entities are already extracted and manifests already parsed. See the offline tension below |
| Test generation | **Build, after a decision** | Genuinely KB-grounded. But "test the code on different scenarios" means *running* generated code |
| Architecture-drift findings | **Build, narrowly** | The groundable slice of "suggest better organisation" |
| Generic improvement / optimisation advice | **Cut** | Ungroundable. Exactly what the citation discipline exists to prevent |
| Runtime log monitoring | **Cut — different product** | See below |

### Runtime log monitoring does not belong

It needs log ingestion, a live connection to a running system, retention, and
alerting. The knowledge base is **static and pinned to a commit** — it knows nothing
about runtime, and cannot. Bolting this on produces two products sharing a login, and
the second one is an observability tool competing with Grafana rather than anything
Codelith is good at.

If it is ever wanted, it is a separate service that *consumes* the KB to explain a
stack trace — not a capability of this feature.

### Test generation needs a sandbox decision, not a prompt

Writing a test is a prompt. *Running* it is arbitrary code execution against a
repository, which needs process isolation, a dependency install, a time limit and a
filesystem boundary. Decide deliberately which of these it is:

* **Write only** — produce test files, let the developer run them. Cheap, honest, and
  most of the value.
* **Write and run** — a real sandbox. A much larger commitment, and the point at which
  Codelith stops being read-only about the user's machine.

Start with write-only. It can be measured against the same standard as everything else:
does the test reference code that exists?

### The offline tension, to be settled before building

"Nothing leaves your box" is the headline claim on the landing page.

A dependency audit has to ask PyPI or npm what the current version is. That is a network
call to a third party, carrying the names of every package the user depends on — which
is a fingerprint of their codebase.

Three ways out, and the choice should be explicit rather than discovered mid-build:

1. **Opt-in**, off by default, stated plainly at the point of use.
2. **Ship an advisory database** and refresh it out of band — offline, staler.
3. **Version-pin analysis only** — no network: unpinned dependencies, conflicting
   constraints, packages imported but not declared, declared but never imported. All
   answerable from the manifest and the import graph alone.

Option 3 is the one that is free, useful, and consistent with the claim. It is the
starting point; 1 and 2 are additions.

---

## The base analysis stays minimal — QA brings its own

QA wants things the other apps do not: call graphs deep enough to trace a finding,
per-symbol test association, dependency constraint parsing. Adding all of that to the
shared analysis would make **every** project pay, in time and storage, for something
most of them never ask for — and it would put QA's vocabulary in the base, which is
the coupling the app split exists to remove.

So an app may run **its own analysis pass on top of the base knowledge base**. The
shared analysis stays the common substrate; QA deepens it when somebody actually opens
QA, keyed to the same commit SHA.

That makes it the first app with two stages rather than one, and it generalises: an
app is defined by what it reads from the KB *and*, optionally, what it derives for
itself. Worth getting the seam right here, because whatever QA does the next one will
copy.

Open question for the build: whether the deep pass is a separate job type with its own
progress, or a lazy step inside the first QA request. A job is more honest about
costing minutes, which it will.

## What it needs from the knowledge base

The registry rule: an app is defined by what it reads. This one reads

* **the graph** — `get_dependents`, `get_blast_radius`, to turn a finding into an impact
* **entities** — `dependency`, `test_suite`, `route`, `cli_command`, `entrypoint`
* **modules** — roles, for drift findings
* **retrieval** — to explain a finding in the surrounding code

Nothing new. Which is the point: if this needs a change to analysis, the change belongs
to everybody, not to QA.

---

## Progress

| Phase | Scope | Status |
|---|---|---|
| Q0 | Prove the seam | ✅ |
| Q1 | Run the tools that already exist | ⬜ |
| Q2 | Give every finding an impact | ⬜ |
| Q3 | Surface coverage | ⬜ |
| Q4 | Dependency audit, offline only | ⬜ |
| Q5 | Architecture drift | ⬜ |
| Q6 | Test generation, write-only | ⬜ |
| Q7 | The deep analysis pass | ⬜ |
| Q8 | The UI | ⬜ |

**Q0 is done and nothing else is started.** Quality appears in the studio as a planned
app — dimmed, unclickable, on both the dashboard and the project hub — and adding it
touched `codelith/apps/registry.py`, a new package, and nothing in
`codelith/knowledge/`. That was the point of the phase: the seam held.

## Phases

Only Q0 is built; everything below it is untouched. The Notes column says what each
phase *contains* rather than what it is called — a phase whose scope is one line is a
phase somebody discovers the scope of halfway through.

Legend: ⬜ not started · 🟨 in progress · ✅ done · ⏭️ deferred

### Q0 — Prove the seam (prerequisite)

| # | Task | Status | What it contains |
|---|---|---|---|
| Q0.1 | Register `qa` in `codelith/apps/registry.py` | ✅ | `built=False`, `needs=(code graph, entities, modules)`, route `/app/projects/{id}/quality` |
| Q0.2 | It renders as a planned card | ✅ | Dimmed on the dashboard and the project hub. Four tests pin it: a planned app is `PLANNED` for *every* KB status, so a ready knowledge base can never make an unbuilt app look live |
| Q0.3 | `codelith/apps/qa/` skeleton | ✅ | Package and `__init__` exist, so the isolation rules apply from the first line. **The router is deliberately not mounted** — see below |

**Exit — met.** Quality appears in the studio as "soon", and adding it touched the
registry, a new package, and nothing in `codelith/knowledge/`.

**On the router.** The original plan said "empty router mounted". It is not, and should
not be until Q8: a mounted router with no endpoints is dead wiring that reads as a
feature somebody forgot to finish, and the app's route (`/app/projects/{id}/quality`)
does not exist yet either. The card is a placeholder by design; the route arrives with
the page that answers it.

### Q1 — Run the tools that already exist

| # | Task | Status | What it contains |
|---|---|---|---|
| Q1.1 | `ToolRunner` | ⬜ | Subprocess with a timeout, working directory, captured stdout/stderr, non-zero exit is data not an error |
| Q1.2 | ruff adapter | ⬜ | `--output-format json` → `Finding(rule, path, line, col, message, severity)` |
| Q1.3 | mypy adapter | ⬜ | `--no-error-summary` line parsing → the same `Finding` |
| Q1.4 | Which tools apply | ⬜ | The `LanguageProvider` decides — Python gets ruff/mypy; a Go repo must not be run through ruff |
| Q1.5 | The repository is not on disk | ⬜ | **The hard part.** Analysis clones and discards. Either re-clone at the analysed SHA, or reconstruct from chunks — chunks are lossy (module-level code is missing), so re-clone |
| Q1.6 | Tests | ⬜ | A tool that is not installed, one that times out, one that returns garbage — none may fail the run |

**Exit:** a findings list from a real repository, with nothing interpreted yet.

### Q2 — Give every finding an impact

| # | Task | Status | What it contains |
|---|---|---|---|
| Q2.1 | Finding → symbol | ⬜ | `path:line` to the enclosing symbol via `KBModule.symbols_json` |
| Q2.2 | Blast radius per finding | ⬜ | `get_dependents` and `get_blast_radius`, cached per path within a run |
| Q2.3 | Documentation impact | ⬜ | Site pages whose `source_files` include the path — "3 written pages cite this" |
| Q2.4 | Ranking | ⬜ | Severity × reach. A `F821` in a leaf script is not a `F821` in the composition workflow |
| Q2.5 | Tests | ⬜ | The ranking is the product; a finding with no impact data must degrade, not vanish |

**Exit:** *"`F821` at `diagram.py:442` — runs in the composition workflow, so this breaks
every documentation job; 3 pages cite the file."* That sentence is the whole feature.

### Q3 — Surface coverage

| # | Task | Status | What it contains |
|---|---|---|---|
| Q3.1 | The surface | ⬜ | `route`, `cli_command`, `scheduled_task`, `entrypoint` entities |
| Q3.2 | Test association | ⬜ | Which test files name each one — graph edge first, then name match |
| Q3.3 | The number | ⬜ | "6 of 28 routes are named in no test", with the six listed |
| Q3.4 | Honesty about the method | ⬜ | Name matching is evidence, not proof. Say so in the UI or it reads as coverage |

**Exit:** a number more meaningful than line coverage, that does not overclaim.

### Q4 — Dependency audit, offline only

| # | Task | Status | What it contains |
|---|---|---|---|
| Q4.1 | Declared vs imported | ⬜ | `dependency` entities against the import graph, both directions |
| Q4.2 | Unpinned | ⬜ | No version constraint at all |
| Q4.3 | Conflicting constraints | ⬜ | The same package pinned differently in two manifests |
| Q4.4 | No network | ⬜ | Deliberate: "nothing leaves your box" is the headline claim. Latest-version checks are a later, opt-in addition |

**Exit:** four checks, no socket opened.

### Q5 — Architecture drift

| # | Task | Status | What it contains |
|---|---|---|---|
| Q5.1 | Role rules | ⬜ | Which `ModuleRole` may import which. Derived from what the codebase already does, not imposed |
| Q5.2 | Violations | ⬜ | `api` reaching into `data_access` past the service layer |
| Q5.3 | New since last KB | ⬜ | Two knowledge bases, two graphs, diff the edges. **The only thing here that uses per-commit pinning**, which nothing else does |
| Q5.4 | Tests | ⬜ | A rule nobody can satisfy produces noise; each rule needs a real violation and a real pass |

**Exit:** "this edge is new since last week" — architectural regression testing.

### Q6 — Test generation, write-only

| # | Task | Status | What it contains |
|---|---|---|---|
| Q6.1 | What to test | ⬜ | Uncovered surface from Q3 — generation aimed at a gap that was measured |
| Q6.2 | Retrieve then write | ⬜ | Same shape as the documentation writer: the KB slice for the symbol, then the test |
| Q6.3 | Grounding check | ⬜ | Does the test import and call things that exist? Same rule as citations: the model proposes, the KB disposes |
| Q6.4 | Write only, no run | ⬜ | Running generated code needs a sandbox. Deliberately out of scope until somebody asks |

**Exit:** a test file a developer runs themselves, that references real code.

### Q7 — The deep analysis pass

| # | Task | Status | What it contains |
|---|---|---|---|
| Q7.1 | What QA needs the base does not hold | ⬜ | Decide from Q1–Q6, not before. Likely: deeper call edges, symbol↔test association |
| Q7.2 | Job or lazy step | ⬜ | A job type is more honest about costing minutes, which it will |
| Q7.3 | Keyed to the commit | ⬜ | Same SHA as the base KB, invalidated together |
| Q7.4 | Stays out of the base | ⬜ | The isolation test is what proves it |

**Exit:** QA deepens the KB for itself, and no other app pays for it.

### Q8 — The UI

| # | Task | Status | What it contains |
|---|---|---|---|
| Q8.1 | Findings inbox | ⬜ | Severity, file, impact, dismiss. **The first app whose output is a worklist** rather than a document or a conversation — so the first that needs dismissal state |
| Q8.2 | Coverage view | ⬜ | The surface, and what is untested |
| Q8.3 | Dependency table | ⬜ | Q4's four checks |
| Q8.4 | Card counts | ⬜ | "N findings" on the dashboard and project hub |

---

## The first thing to do when this starts

Run `ruff check app/ --select F821` and fix what it finds, then decide whether ruff
belongs in CI. The only current hits are SQLAlchemy `Mapped["Project"]` forward
references, which are false positives and need silencing first.

It is a small task, and it is this whole feature in miniature: the tool already exists,
the answer is already available, and nobody is looking at it.
