> **How to use:** paste this whole file. Attach [03-api-contract.md](03-api-contract.md),
> the approved first-screen design, screenshots of the current build, a real generated
> document, and a real `knowledge-base` JSON response — see [README.md](README.md).

---

# Design the Document Anything studio

You have already designed and I have approved the front door. Now design the
application behind it. Everything here is about **what each screen has to do and what
information it has to carry** — the visual language stays yours, and it should follow
from what you established in the approved direction.

## The product, in one paragraph

Document Anything reads a codebase and writes technical documentation from it, running
entirely on the user's own machine against a local LLM. It works in two phases:
**analyse** the repository once to build a knowledge base, then **compose** as many
documents as you like from that knowledge base without ever re-reading the code.

## The one thing that makes this hard

**Everything takes minutes, not milliseconds.**

Analysis is roughly **3 minutes**. Composing two document types is roughly **7 minutes**.
On a slower local model, longer. These are not spinners — they are seven-stage and
nine-stage pipelines where each stage does visible, describable work, and the user is
sitting there deciding whether to trust it.

So the studio's real job is not CRUD screens. It is:

- making a long wait **legible** — what is happening, what has been produced so far,
  how much is left, and whether it is safe to walk away (it is: work continues
  server-side and the page can be closed);
- making the knowledge base **feel real** — proving the tool understood the code, with
  the actual modules, routes and dependencies it found, not a row of counters;
- making **cancel** obviously available and obviously honest. Cancellation genuinely
  aborts generation mid-stream, and the UI must never claim a state the backend is not
  in.

If those three land, the product works. If they do not, nothing else saves it.

## Who uses it

One authenticated user, working alone or in a small team. Roles exist
(`admin` / `manager` / `reviewer` / `viewer`) and gate a few actions — creating projects,
starting jobs, cancelling and approving need `manager` or above; `viewer` can read
everything. Design for the full-permission case and degrade gracefully; do not build a
permissions UI.

---

## The end-to-end journey

Follow this closely — it is the actual flow, and the data listed at each step is exactly
what the API returns. Field names, enums and shapes are in the attached API contract.

### 1. Sign in

Email and password, returns a JWT pair. Register is open. There is no email
verification, no SSO, no password reset today.

### 2. Create a project — with its first source, in one step

A project is a codebase plus everything generated from it. Creating one **requires a
source** — a GitHub/GitLab/Bitbucket URL, a local path, or an uploaded zip.

The interesting part, and worth designing properly: **the source is fetched and
inspected before the project is created.** A separate probe call clones the repo, counts
the files and reports what it found. Only then is anything written. So the creation flow
can be a genuine conversation rather than a form that fails afterwards:

- the user provides a URL (and optionally a branch);
- we fetch it — this takes a few seconds and can fail in specific, explainable ways
  ("Repository not found. Check the URL and that it is public.", "That branch does not
  exist.", "Fetched fine, but there is nothing here we can analyse.");
- on success we can show **what is actually in there before committing to it**:
  `file_count`, `analysable_files`, the language breakdown as a map of
  `{"python": 170, "markdown": 22}`, the resolved `commit_sha`;
- the project name can be suggested from the repo slug;
- then, and only then, the project exists.

A failed probe must leave nothing behind. This flow used to create the project first and
swallow the error, and users were left cleaning up empty projects.

### 3. Analyse

The user triggers analysis. It takes no document type — the whole point is that you
choose what to write *after* the tool knows what is there. This starts a job with
`job_type: "analysis"` running seven stages:

| Stage | What it does | What it reports when done |
|---|---|---|
| `repo_analyzer_agent` | Clones and reads every parseable file | files read, sources processed |
| `structured_extractor_agent` | Groups files into modules; extracts routes, dependencies, env vars, entry points | modules mapped, facts found |
| `semantic_indexer_agent` | Embeds the source so sections can later be written from the right code | chunks indexed, failures |
| `module_summarizer_agent` | Writes a short summary per module, reused by every future document | modules summarised, failures |
| `architecture_synthesizer_agent` | Assembles summaries into how the system fits together | components identified |
| `narrative_writer_agent` | Writes cross-cutting prose — request lifecycle, auth, config, deployment | narratives written, skipped |
| `kb_persister_agent` | Stores everything | knowledge base ready / degraded |

Each stage carries `status`, `started_at`, `completed_at`, a computed `duration_seconds`,
and an `output_json` blob holding those measured numbers. **That is what makes the
progress view worth looking at** — every completed stage can state what it produced:
*"Mapped 45 modules and found 77 facts"*, *"Indexed 1,204 chunks"*, *"Summarised 30
modules"*. Never show a raw agent name to a user. The attached API contract lists which
keys each stage reports, and the current build already has tuned copy per stage in
`ui/src/app/lib/narrate.ts` if you have the repo to hand.

Stages run in sequence, so at any moment one is running, some are done and some are
queued. There is also a live log stream (SSE) — useful, but it is debug output and
should not be the main event. Analysis can be cancelled at any point.

### 4. The knowledge base — the payoff screen

When analysis finishes the project has a knowledge base, keyed to the commit SHA, with
status `ready` or `degraded` (built, but a stage failed — usable with a warning).

One API call returns everything this screen needs, and it is rich. It is the most
information-dense screen in the product and probably the most important to get right:

- **counts** — modules, extracted facts, languages, breakdown by module role
  (`api`, `service`, `data_access`, `model`, `schema`, `worker`, `infra`, `test`, …) and
  by fact kind (`route`, `entrypoint`, `dependency`, `env_var`, `datastore`,
  `external_api`, `cli_command`, `scheduled_task`, `infra_resource`, …);
- **the evidence** — and this is what makes it land rather than read as a progress bar
  that ended:
  - `top_modules`: real paths, names, inferred roles, lines of code, and the
    **LLM-written summary of each module** (a paragraph, not a label);
  - `sample_routes`: actual endpoint paths that were found;
  - `key_dependencies`: real package names;
  - `entrypoints`: how the thing is started;
  - `narrative_topics`: which cross-cutting stories were understood;
- **the commit SHA** the knowledge base was built from, and when.

Then the actual decision: **`suggested_doc_types`** — which documents are worth writing,
each with a `confidence` (0–1) and a `reason` written from the evidence:

```
architecture      0.90   "45 modules mapped across the codebase"
api               0.95   "28 HTTP routes detected"
getting_started   0.70   "3 entrypoints and 46 declared dependencies"
deployment        0.60   "4 infrastructure definitions found"
modules           0.60   "several service and utility modules worth documenting individually"
```

Nothing is offered without evidence — a project with no HTTP routes never sees "API
Reference". The user picks one or more, picks output formats
(Markdown / DOCX / MkDocs / Docusaurus), optionally asks for a human review gate, and
composes.

Each doc type needs a real explanation of what that document will contain, not just a
title. An API Reference means routes, authentication, request and response shapes, error
handling. An Architecture doc means components, layers, how a request flows, why it is
built that way. Users are choosing between things they have not seen yet.

The knowledge base can also be **re-analysed** — necessary when the code has moved on,
since it is pinned to a commit.

### 5. Compose

Starts a second job (`job_type: "composition"`), nine stages:

| Stage | What it does |
|---|---|
| `kb_loader_agent` | Opens the knowledge base — the code is not read again |
| `composition_strategy_agent` | Decides audience and depth |
| `composition_planner_agent` | Outlines each document and picks the source files every section needs |
| `composition_writer_agent` | Writes each section from retrieved source — by far the longest stage |
| `diagram_agent` | Generates Mermaid diagrams |
| `qa_agent` | Verifies claims against the source and reviews quality |
| `gate` | Human review decision point |
| `formatter_agent` | Injects diagrams, renders the requested formats |
| `publisher_agent` | Saves the finished documents |

Same progress model as analysis. Two wrinkles: `diagram` and `qa` run **in parallel**,
and when human review is requested the job ends in `awaiting_review` (there is a known
backend limitation here — approval cannot currently resume the graph; design the state
as visible and honest, do not design a rich approval workflow around it).

### 6. Read the documents

Composition produces documents — 15,000 to 40,000 characters of Markdown each, with
headings, tables, fenced code in several languages, Mermaid diagrams, lists and
blockquotes. Real documents from this tool routinely contain **25+ tables and 60+ code
blocks**.

This is long-form technical reading and should be designed as such: comfortable measure,
navigable structure, code that is genuinely readable. Documents have a type, a version, a
status (`draft` / `review` / `published`), the job that produced them, and can be
edited, published and exported.

Users arrive at a document from different places — from the project, from a job, from the
global document list — and must be returned to where they came from.

---

## Screens to design

| Screen | What it exists to do |
|---|---|
| **App shell** | Navigation across projects, documents and settings; identity and sign-out; a persistent, glanceable signal that a job is running somewhere, because the user will navigate away from it |
| **Dashboard** | The state of the workspace at a glance, and the fastest possible route back into whatever the user was last doing. Projects, activity, recent documents, anything running now |
| **Projects list** | Scan and pick a project. Each row should say enough to make the choice without opening it: sources, whether it has been analysed, jobs, documents, last activity |
| **Create project** | The probe-first conversation described above, including the failure cases and the "here's what's in it" moment |
| **Project detail** | The hub, and the busiest screen: sources; knowledge-base state (never analysed / building / ready / degraded / stale); the evidence panel; the doc-type picker; job history; documents. Its hardest problem is that it means something entirely different before and after the first analysis |
| **Job progress** | A multi-minute, multi-stage pipeline made legible: what is running, what each finished stage produced, elapsed time, that it is safe to leave, and cancel. Debug logs available but not dominant |
| **Documents list** | Every document across every project, grouped by project, searchable |
| **Document reader** | Long-form technical reading, and the actions around a document (export, publish, edit, back to origin) |
| **Settings** | Local LLM configuration — endpoint, API key, three model slots (default / fast / quality), temperature, max tokens. Dull but it must not look abandoned |

### States that must be designed, not left to chance

These are where this kind of app usually falls apart:

- **First run** — no projects at all. This is the most important empty state in the
  product and the user's first impression after signing in.
- **Project with a source but never analysed** — the call to action is analysis, and
  nothing else on the screen should compete with it.
- **Analysis running** — including navigating away and coming back mid-run.
- **Analysis failed**, and **degraded** (finished, but a stage failed — usable with a
  warning).
- **Cancelled** — deliberate, not an error. Stages that never ran are skipped, not
  pending forever.
- **Knowledge base stale** — code has moved past the analysed commit.
- **Composing** while a knowledge base already exists — analysis is done and untouched.
- **Awaiting review**.
- **A document that is empty or malformed**, and a project whose analysis produced very
  little.
- **Loading** for every list and panel — real skeletal structure, not a centred spinner.

---

## Constraints

- **Light theme, orange accent**, per the approved direction. Build tokens so a dark
  theme can be added later; ship light.
- **Fully offline.** No external fonts, scripts, images or analytics — inline or bundle
  everything.
- **Motion is welcome and expected**, and must respect `prefers-reduced-motion`. But no
  animation may sit between the user and information about a running job — the screens
  people stare at for minutes are the ones where cleverness costs the most.
- **Keyboard and focus states are part of the design**, not a later accessibility pass.
  Contrast has to hold at typical laptop brightness; orange on white is easy to get
  wrong.
- Real content only. Every number, path, summary and reason in these screens comes from
  the API — design against the real payloads attached, including the ugly cases: a
  180-character module path, a 400-character module summary, a repository with 4 modules,
  a repository with 300.

## Deliverable

Self-contained HTML files I can open in a browser — one per screen, or a small
click-through set, all CSS and JS inline, no external requests, responsive, and showing
real states rather than one happy path.

Priority order, in case you want my sign-off before doing all of it:

1. **Project detail** (post-analysis, knowledge base ready) — the densest screen and the
   product's centre of gravity
2. **Job progress**, mid-run — the hardest, and the one that decides whether the wait is
   tolerable
3. **Project detail** (pre-analysis) and **create project**
4. **Document reader**
5. **Dashboard**, **projects list**, **documents list**
6. **Settings**

Along the way, tell me anything the flow gets wrong. You are seeing it end to end, and
if the two-phase split is confusing at a screen I have stopped being able to see, I want
to know.
