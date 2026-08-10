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

## Sketch of the phases

| # | Phase | Notes |
|---|---|---|
| Q1 | Runner for existing tools | ruff, mypy; capture structured output. Repo-agnostic, so language providers decide which tools apply |
| Q2 | Findings joined to the graph | Every finding gets an impact: what imports it, what documentation cites it |
| Q3 | Surface coverage | Routes, CLI commands and scheduled tasks named in no test. Cheap, and a more meaningful number than line coverage |
| Q4 | Dependency audit, offline slice | Unpinned, conflicting, imported-but-undeclared, declared-but-unused |
| Q5 | Architecture drift | Role violations against the import graph — `api` reaching into `data_access` |
| Q6 | Test generation, write-only | Measured the same way: does the test reference code that exists |

**Prerequisite:** the feature-module restructure. QA is the third feature and the first
one built into the new structure — which makes it the test of whether the seam holds.

---

## The first thing to do when this starts

Run `ruff check app/ --select F821` and fix what it finds, then decide whether ruff
belongs in CI. The only current hits are SQLAlchemy `Mapped["Project"]` forward
references, which are false positives and need silencing first.

It is a small task, and it is this whole feature in miniature: the tool already exists,
the answer is already available, and nobody is looking at it.
