# The apps

Everything below reads the knowledge base. None of it re-opens the repository, and nothing
in one app can see another.

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

**Reads:** the files each reading kept, modules, entities, written pages, architecture.

The difference between two readings of the same repository. It needs the codebase
analysed at two commits: one reading is a photograph, two are a difference. Any two
readings can be picked at the top of the page.

**Files**, first: every file added, changed, removed or moved, line by line, side by
side or unified, with the words that changed within a line marked and long runs of
unchanged lines folded. Over each file is what the later reading knows about it: its
part, how many files depend on it, whether a test reaches it, and the written pages
that cite it — the blast radius of the change, beside the change. `j` and `k` step
through the files.

Every reading keeps its files, each distinct content stored once, so nothing is lost
between readings. A reading taken before that was kept can have its files fetched
from git at its commit, from the same page, without reading the code again.

**What it means**, the second tab:

- **Modules** added, removed, grown, shrunk or rewritten, with line deltas.
- **Entities** that came and went — a route removed, an env var no longer read.
- **Components** added, removed, retyped or **renamed**.
- **Relations** between components, opened or cut.
- **Written pages at risk** — pages that describe code that has since moved.

**Commits**, the third: the commits between the two readings — exactly what git would
list, reachable from the later reading's commit and not from the earlier one's — each
opening to the files it touched, each file to its diff. Analysis keeps the commits it
reads (hash, author's name, date, subject, files; never an email). For readings taken
before that, **Fetch the history** reads them from the source: a local folder is only
read, a repository on a host is cloned without file contents and removed after.

**History**, a page of its own (from the codebase page's *Over time*): every reading
newest first, each against the one before — files and lines changed, the parts they
belong to, the commits between — with *Compare with the one before*, *Compare with…*
any other, and *Browse its files* as they were. A file's own history (from the knowledge
graph's side pane) lists the readings where it changed, each opening that diff. Each
point on *Over time* opens the comparison for that step.

How much the kept files take is on the Settings page; `KEEP_SOURCE_READINGS` keeps only
the newest few readings' files per codebase, and deleting a codebase frees what only it
used.

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

## Review a change

**Reads:** code graph, entities, written pages, the parts the architecture pass named.

The same knowledge, after the edit: a change — uncommitted, or between two commits —
checked against what the reading knows. What it touches, file by file and function by
function; what could break; which tests to run and which written pages to check; what
it adds or removes that the outside world sees; and whether it fits the codebase's
shape. The shape is the knowledge graph's columns — where work comes in, core logic,
shared helpers, data and outside services — so an import that runs backwards against
them, a new dependency between two parts, or a new loop is said out loud, with the
file and line.

On the codebase's **Review** page in the studio (which can review the working copy
itself when the codebase is a folder on this machine), as `codelith review` in a
checkout — exit code 1 when there is something to stop for — and to an agent as the
[`review_changes`](mcp.md#review_changes) MCP tool. Every review is kept on that page,
wherever it was run.

## Tour

**Reads:** code graph, flows, narratives, entities, the parts the architecture pass named.

A guided walk for someone new to the code, on the knowledge graph: what it is, how it is
laid out, where work comes in, one real request followed from its handler to its data,
the core, where the data lives, the helpers everything leans on, and the files where an
edit hurts most. Each stop opens its parts, lights its files on the map and — for the
request — plays its flow underneath. **Take the tour** on the codebase page or in the
graph; where you stopped is remembered in your browser.

No model call. The words are the opening sentences of what analysis already wrote, and
facts with a file behind them; a tour can be thin on a codebase the reading knew little
about, but it cannot describe something that is not there. **Copy as Markdown** on the
last stop gives the same tour as a document, for a README or an onboarding page.

---

## Health over time

Not an app — it adds nothing of its own — but it is on every codebase page.

**Where danger collects** ranks files by how often they changed (the last 90 days, or
the whole history when those were quiet), weighted by how much of the code depends on
them and whether a test reaches them. The history is read from git while the checkout
exists and kept with the reading; a clone from a host is deepened for the window first,
never a folder of your own. The same files can be lit on the knowledge graph with
**Hotspots**.

**Over time** shows each kept reading: files, lines, imports between parts, and imports
that run against the columns — with the ones that are new since the reading before. A
point opens what changed at that step; *Every reading* opens the History page.

---

## QA

**Reads:** the files the reading kept, the code graph, the flows, the risk ranking, facts.

What a QA engineer checks, starting from what Codelith already knows about the code. Pick
the areas, how deep, and how much of the code:

| Area | What it looks for |
|---|---|
| Security | SQL, shell and code built from values; unsafe deserialisation; TLS or JWT checks off; weak hashing or `random` for secrets; CORS open with credentials; debug on; routes that reach data with no auth step; request data followed through the recorded calls to a query, a shell, a file path or an outbound URL |
| Data leakage | keys, tokens and passwords in code, config, CI and images; a committed `.env`; credentials in logs; exception text sent to clients |
| Dependencies & compatibility | imported but not declared; dev-only packages in shipped code; declared and never imported; unpinned with no lockfile; lockfile drift; syntax newer than the declared Python; images older than the code needs. **Online, only if you tick it:** known vulnerabilities (OSV.dev), how far behind, licences |
| Error handling | exceptions caught and dropped, bare `except`, empty `catch`, ignored errors, network calls with no timeout |
| Things that will break | mutable defaults, `is` with a literal, environment variables the code needs that nothing declares |
| Performance & concurrency | blocking calls inside async code |
| Configuration & deployment | containers running as root, unpinned images, `COPY .` with no `.dockerignore`, databases published on every interface, placeholder secrets in compose, CI actions not pinned, script injection and echoed secrets in CI |
| Tests | routes and commands no test reaches, ranked by what they touch; tests that assert nothing |

Every finding points at an exact line and says how sure it is: **confirmed** (an exact
pattern, a tool, or a test that fails), **likely** (a heuristic that is usually right, or
a designed test that fails) or **suspected** (a model's, checked twice). It says what it touches — the part, what depends on the file, the routes
that reach it, whether a test does, the pages that cite it — and how to fix it.

A finding is recognised again by the next run from its rule, its file and the code
itself, not its line number: the run says what is **new** and what was **fixed**, and a
finding dismissed as not a problem, or accepted as a risk, stays that way, with its
reason, after the line moves. `codelith: ignore` written on a line silences it there.

A secret is never copied: a finding records where the value is, and the code is shown
with it masked. Nothing leaves the machine; checks that would (known vulnerabilities in
dependencies) arrive as a choice per run, off by default, saying what they send.

Findings a public route reaches say so, with the chain of calls from the route, and a
security finding behind one is raised a level. What the online check sends is in the
run's notes: package names and versions to OSV.dev, package names to PyPI, npm and the
Go proxy — never code or file names.

**Thorough** adds the quality model's review of the riskiest functions (ranked by what
depends on them, whether a test or a public route reaches them, whether they touch data).
Every claim must quote its line; a quote not where it says is dropped, and each claim
left is put to a second call that sees only the claim and the code. What survives is
marked *suspected*. How many functions it reads is `QA_REVIEW_TARGETS`.

**Run tests** adds the sandbox, in Docker. A fresh copy of the reading's commit is
installed in a throwaway container of the image the code asks for (`python:3.11-slim`
for `requires-python = ">=3.11"`) — the only step with a network. The tests and the
codebase's own tools (ruff, mypy, tsc, go vet, when it declares them) then run in a
second container with no network, a read-only root, no capabilities, a non-root user,
memory, CPU and time limits, and none of this machine's environment: no key of yours is
ever inside. What comes back is **confirmed**: a clean install that fails, each failing
test with its output, each problem a tool reports (style rules are left out).

Then the model designs tests — first to reproduce a suspected finding, then for the
riskiest functions no test reaches (`QA_DESIGN_TARGETS`). It lists the cases, writes the
file in the codebase's framework and style, and the sandbox runs it. A failure is
judged by a second call: the code's fault becomes a finding (*likely*, since the model
wrote the expectation) with the failing output and the test attached; the test's fault
gets the test corrected and run again, twice at most. Every designed test is kept with
the run — passing ones are coverage the code did not have — and the ones worth keeping
download as a ZIP at the paths they ran from.

Run tests needs Docker running, and Codelith run from source: inside its own container
it cannot start others. The run dialog says which, before you start.

**Fixes.** Where the line settles it — a bare `except:`, `verify=False`, `yaml.load(`, a
request with no timeout, a weak hash, a dependency below its fixed version — the finding
carries a patch, shown in the diff viewer and ready for `git apply`. When the sandbox ran,
every patch is applied to its copy and the tests run again; a patch after which no test
newly failed says so.

**Exports.** A run downloads as a **fix plan** — Markdown, open findings by severity and
quickest first, each with its fix and patch, ready to tick off — or as **SARIF 2.1.0** for
GitHub code scanning. `codelith qa --fail-on high` runs QA from a CI step and fails it on
what is open.

**Everywhere else.** Ask cites findings when a question is about security, bugs, leaks,
dependencies or tests, says which of those areas QA never checked, and offers a run for
them. `qa_findings` serves them over MCP; `before_edit` lists a file's; `review_changes`
says which a change fixes or touches. AGENTS.md lists the open critical and high ones,
the map lights the files that have any, and the codebase page counts what is open.

