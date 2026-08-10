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
| Q1 | Run the tools that already exist | ✅ |
| Q2 | Give every finding an impact | ✅ |
| Q3 | Surface coverage | ✅ |
| Q4 | Dependency audit, offline only | ✅ |
| Q5 | Architecture drift | ✅ |
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
| Q1.1 | `run_tool` | ✅ | `codelith/apps/qa/runner.py`. Timeout, cwd, captured output; a killed process is reaped so cleanup can delete the checkout |
| Q1.2 | ruff adapter | ✅ | JSON → `Finding`. `E9`/`F81`/`F82` are errors — they break at runtime — everything else is a warning |
| Q1.3 | mypy adapter | ✅ | Line parsing. `note:` lines are continuations, not findings; counting them tripled the number and buried the errors |
| Q1.4 | Which tools apply | ✅ | **QA maps language → tools, not the provider.** A `qa_tools()` method on `LanguageProvider` would put this app's vocabulary in the base |
| Q1.5 | The repository is not on disk | ✅ | `checkout.py` re-clones. Chunks were rejected: reconstructing a file from them loses module-level code — measured, five real `os.getenv` calls went missing |
| Q1.6 | Tests | ✅ | 33. Not-installed, timeout, non-zero exit, binary output, unparseable JSON |

**Exit — met.** 468 ruff findings and 1,539 mypy findings from Codelith itself.

**Two things the first real run exposed.** Ruff reports **absolute** paths even when
invoked as `.`, and the knowledge base stores repository-relative ones — every join in
Q2 matches on that string, so the mismatch produces findings with no impact rather
than an error. Silent, so it is pinned by four tests.

And mypy returned **0 findings, exit 2**: Codelith keeps `repos/` and `runs/` for
clones and job artifacts, mypy walked into them, found four copies of the same
analysed project and gave up with "duplicate module". A report that reads clean
because nothing looked is the worst possible output. Both tools now exclude the base's
`DEFAULT_IGNORED_DIRS` — reused rather than restated, so the two lists cannot drift.

**Known gap, carried forward.** The checkout is not pinned to the analysed commit: the
ingesters take a branch, not a revision, so a re-clone gets the branch head. `Checkout`
reports both SHAs and `drift_note` says so rather than pretending they match.

### Q2 — Give every finding an impact

| # | Task | Status | What it contains |
|---|---|---|---|
| Q2.1 | Finding → symbol | 🟨 | **Only where unambiguous.** See the note |
| Q2.2 | Blast radius per finding | ✅ | Cached per path, not per finding: 409 findings across dozens of files is dozens of traversals, not 409 |
| Q2.3 | Documentation impact | ✅ | Written pages only — a planned page cites nothing yet, and naming it would be a claim about the future |
| Q2.4 | Ranking | ✅ | Severity dominates; reach breaks ties; a cited page counts for five importers. Reach is capped at 40 |
| Q2.5 | Tests | ✅ | 19. Including that a finding with no impact keeps its place in the list |

**Exit — met.** On neurosurfer: 409 findings, and the top of the list is
`union-attr` in `observability/logging.py` — *46 files reach it* — above two hundred
others.

**Why reach is capped.** A file 200 modules import is not twice as urgent as one 100
import; both mean load-bearing. Uncapped, the single most-imported file takes every
slot at the top and nothing else is ever read.

**Q2.1 is partial, and the reason is the case for Q7.** The knowledge base stores
symbols per *module*, and a module is usually several files — so a symbol at line 47
could belong to any of them. Attributing anyway would put a finding inside a function
from a different file, and a reader cannot tell a confident wrong answer from a right
one. Only single-file modules are attributed, which on neurosurfer is almost none.
Per-symbol file attribution is exactly what a QA-specific analysis pass should derive
rather than making every project's analysis carry.

### Q3 — Surface coverage

| # | Task | Status | What it contains |
|---|---|---|---|
| Q3.1 | The surface | ✅ | Routes, CLI commands, scheduled tasks, entrypoints. Not every entity kind — "this datastore has no test" is not a sentence anybody acts on |
| Q3.2 | Test association | ✅ | Name matching against test-file chunks, per kind. A route matches its *path*, not its verb |
| Q3.3 | The number | ✅ | On neurosurfer: **9 of 9 named in no test**, all nine listed |
| Q3.4 | Honesty about the method | ✅ | Every string says "named in a test", never "covered". Four tests pin the wording |

**Exit — met**, and the number is real: neurosurfer has 30 test files and not one
contains the string `health`, so its four routes genuinely have no test naming them.

**One false positive, found and fixed.** The CLI command is `neurosurfer`, which appears
in every import line of every test — a substring search reported it covered by
`tests/fakes.py`, which tests nothing of the sort. Command names are now matched
**quoted only**, because a test that invokes a command passes its name as a string.

**The wording is load-bearing.** Name matching finds a route nobody mentions reliably
and never finds one exercised through a fixture, so this is a *floor on what is
untested*, not a measure of what is tested. A number people trust that does not mean
what they think is worse than no number — which is why nothing here says "covered".

### Q4 — Dependency audit, offline only

| # | Task | Status | What it contains |
|---|---|---|---|
| Q4.1 | Declared vs imported | ✅ | Both directions, from the graph's `Package` nodes — the language providers already separated third-party from local and stdlib |
| Q4.2 | Unpinned | ✅ | |
| Q4.3 | Conflicting constraints | ✅ | Name-normalised, so `Python-Slugify` and `python_slugify` are not a conflict |
| Q4.4 | No network | ✅ | No socket. Latest-version checking stays a later, opt-in addition |

**Exit — met.** On neurosurfer: 17 of 43 dependencies need a look — 9 imported but
undeclared (`starlette`, `torch`, `numpy`), 3 unpinned, 5 with no import found.

**The first run reported 22, and five of them were wrong.** Two families of false
positive, both fixed:

* **Plugins are configured, not imported.** A mkdocs plugin is named in `mkdocs.yml`
  and never appears in a `.py` file — eight of the nine "unused" findings were exactly
  this. Whole prefixes are excluded now (`mkdocs-`, `pytest-`, `sphinx-`, `types-`).
* **Namespace packages.** `import opentelemetry`, install `opentelemetry-sdk`.
  Declaring the distribution is correct, and both directions now resolve it.

**"Unused" is the weakest of the four and the wording says so.** It can only see
imports the analysis recorded — a package loaded by string name looks unused — so the
detail reads "no import of it was found in the analysed code" rather than "it is
unused". The first is what was measured.

### Q5 — Architecture drift

| # | Task | Status | What it contains |
|---|---|---|---|
| Q5.1 | Role rules | ✅ | Derived at 10:1 over at least 8 edges. Below that it is two conventions coexisting, and picking a winner is an opinion |
| Q5.2 | Violations | ✅ | On neurosurfer: `service → cli`, one import, against 33 the other way — with the file pair |
| Q5.3 | New since last KB | ✅ | Compares against the previous build's roles. `None` when there is no earlier build, so a first run never claims something is "new" |
| Q5.4 | Tests | ✅ | 12, including the ordering bug below |

**Exit — met.** Two rules derived from neurosurfer (`cli → service` ×33,
`cli → config` ×8) and one violation found: `neurosurfer/__main__.py` imports
`neurosurfer/app/cli/__init__.py`.

**A real bug, and the first run hid it completely.** Rules were tested in whichever
direction the counter yielded first, so meeting `service → cli` (1 edge) before
`cli → service` (33) discarded the pair — the clearest rule in the codebase was
invisible because of dict ordering, and the run reported *no violations at all*. The
dominant direction is now chosen explicitly, and a test asserts both orderings agree.

**Rules are derived, never imposed.** A layering rule written into this file would be
a judgement about somebody else's architecture, and the first thing anybody does with
an opinionated linter is turn it off. A codebase with no discernible layering gets no
rules and no findings, which is the right answer for one that has none.

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
