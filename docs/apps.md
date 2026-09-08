# The apps

Four things read the knowledge base. None of them re-open the repository, and none of
them can see each other.

An app is defined by **what it needs from the knowledge base**, and optionally by what
it derives for itself. Derived data stays inside the app, so a project that never opens
one never pays for it.

!!! note "The isolation is a test, not a convention"
    `tests/unit/test_module_isolation.py` fails if the base imports an app, or if one
    app imports another. Known exceptions live in `KNOWN_LEAKS` with a reason, and that
    list can only shrink.

    Adding an app should mean one entry in `codelith/apps/registry.py` and one page. If
    you find yourself editing an analysis agent to add one, stop: the app is asking for
    something the knowledge base should hold for everyone.

---

## Documentation

**Reads:** retrieval, narratives, entities.

Writes structured documents from the stored analysis: Markdown, DOCX, HTML, MkDocs or
Docusaurus.

Document types are offered from an **evidence-backed menu**. A project with no HTTP
routes is never offered an API reference — not because that would be rude, but because
the resulting document would be invented.

Composition is retrieve-then-write, per section. The pipeline does the retrieval
deterministically in Python, and the model does one thing: write. Retrieval is still
available at write time as a bounded follow-up query, but not as an open-ended
exploration loop.

??? note "Why the writer is not an agent with filesystem tools"
    It used to be. Measured on one job that was 21 `read_text_file` calls, zero uses of
    the retrieval layer already built for it, an MCP server spawned per section, and 55%
    of total runtime.

Sites can be published to a capability URL — unguessable, shareable by copying, revoked
by minting another — and carry a source page per cited file, so a citation in the prose
resolves to the code it came from.

---

## Ask the code

**Reads:** retrieval, code graph, entities.

A question, answered from the analysis, with **every citation checked against the
evidence actually retrieved**. A citation that does not resolve is stripped rather than
shown.

One retrieval pass answers most questions. The model is given the evidence and a set of
tools together, so reaching for a tool *is* the escalation signal and a turn that does
not reach for one has already streamed the answer.

The tools are the same ones exposed [over MCP](mcp.md), so an escalation can search by
name, read a file, find callers, or list facts — and everything a tool returns is
appended to the bundle, so the citation check covers it exactly like pre-loaded
evidence.

**Not every question is searched.** A gate runs before retrieval and can decide the
answer is not in this repository — the one thing the router structurally cannot say,
because everything handed to it is routed. It judges against what analysis found this
codebase to *be*, not against a general idea of what a programming question sounds
like: a codebase about elections makes "which countries are reconciled" a question
about its data, and a codebase about compilers does not. It reads the last few turns
too, so a follow-up that names nothing on its own is still read in the conversation it
belongs to. Every uncertain path answers "search it" — see
[`ASK_SCOPE_GATE`](reference/configuration.md#ask-the-code).

The suggested questions come from `question_seeder`, not from a template.

---

## What changed

**Reads:** modules, entities, written pages, architecture.

The difference between two readings of the same repository. It needs the codebase
analysed at two commits: one reading is a photograph, two are a difference.

It reports:

- **Modules** added, removed, grown, shrunk or rewritten, with line deltas.
- **Entities** that came and went — a route removed, an env var no longer read.
- **Components** added, removed, retyped or **renamed**.
- **Relations** between components, opened or cut.
- **Written pages at risk** — pages that describe code that has since moved.

??? note "Why renames are a category of their own"
    Component names are written by a model, and two readings of an unchanged repository
    do not agree on them: "HTTP API" one run, "Codelith API" the next.

    Keyed on name alone, a diff whose real content was two new files reported *nine
    services appeared, eight went, twelve connections broke*. Components are now paired
    on the **modules they contain**, which come from the code, and the same comparison
    reads *two appeared, one went, seven renamed*.

---

## Before you edit

**Reads:** code graph, entities, written pages.

What a change to a file or symbol would touch, assembled before you make it: importers,
transitive reach with distance, call sites, whether a test reaches it, declared routes
and env vars, and the written pages that cite it.

In the studio it sits under whatever file you are reading. To an agent it is the
[`before_edit`](mcp.md#before_edit) MCP tool.

No model call and four indexed queries, which is the point: a check an agent skips
under time pressure is a check that does not exist.

The failure it prevents is not a wrong edit but a **confidently narrow** one — correct
in the file, and broken for four callers nobody looked for.

---

## Quality

Not on `main`. It was built — ruff and mypy findings ranked by what each one touches,
surface with no test, an offline dependency audit, derived layering rules — and then
deliberately taken back out until Documentation and Ask settle. An app maturing against
two neighbours still changing shape is an app rebuilt twice.

It lives on the `feat/qa` branch, and `.dev/QA_AGENT_PLAN.md` is the record of what was
deliberately not built.
