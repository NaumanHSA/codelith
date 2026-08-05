# UX Overhaul Plan

Status: **complete** · Created 2026-08-05 · Delivered 2026-08-05 · Details in [UX_PROGRESS.md](UX_PROGRESS.md)

Separate initiative from the analyse/compose rearchitecture in [PLAN.md](PLAN.md),
which is complete through Phase D. That work made the product *correct*; this makes it
feel finished.

## What's actually wrong

Grouped by cause, because several "design" complaints are really bugs.

### Genuine bugs (verified)

| # | Symptom | Root cause |
|---|---|---|
| B1 | Cancelling a job stops the UI but LM Studio generates to completion | `cancel()` only flips a DB column. No Celery `revoke()`, no cooperative abort, no streaming — the in-flight request runs to the end |
| B2 | neurosurfer suggests no API Reference despite 28 route decorators | `PythonProvider._walk` recurses into `ClassDef` but **not** `FunctionDef`. neurosurfer registers routes inside `mount_chat_routes(router, server)`, so they are invisible |
| B3 | "43 Dependencys", "24 Env Vars" | Naive `+ 's'` pluralisation |
| B4 | Markdown tables and some code blocks render as raw text | `SimpleMarkdown` is hand-rolled with no table support |
| B5 | Adding a GitHub source creates the project even if the repo is bad | Project is created first; the source is never validated |
| B6 | Opening a doc from a project, then Back, lands on all-documents | Viewer always links back to `/app/documents` with no origin context |
| B7 | Settings exposes doc templates | Nothing reads them — `system_settings` templates are write-only |

### Design and interaction

- Cards are static: no hover, no affordance, nothing clickable.
- Rows end in a tiny "View" link instead of the row itself being the target.
- Rows are information-poor.
- The knowledge base card shows counts but not **what we actually found**.
- The doc-type picker is a grid of unexplained tiles — "Architecture" with no
  explanation of what that document would contain.
- The analysis view is a flat checklist with debug logs; no sense of progress, no
  human-readable narration, no signal that it is safe to leave.
- The document viewer is two columns; it should be one centred reading column.
- The Documents page mixes every project together.

## Principles

1. **The row is the target.** Whole rows and cards are clickable, with hover, focus-visible
   and active states. No "View" links.
2. **Say what happened, not what ran.** `structured_extractor_agent` → "Mapped 45 modules
   and found 77 facts". Debug logs are for the trace files on disk, not the user.
3. **Show the evidence.** Counts alone are not knowledge. Show the routes, the modules,
   the languages — the things we actually extracted.
4. **Never lie about state.** If the UI says cancelled, the work is cancelled.
5. **One reading column** for documents.
6. **Dark-first, one system.** Everything through the tokens in `styles/theme.css`.

## Phases

Ordered so foundations land first and each phase is independently shippable.

### U1 — Design system foundation ✅
- [x] Extend `theme.css`: elevation scale, focus ring, motion tokens, radius scale
- [x] Interactive primitives: `Row`, `ClickableCard`, `IconButton`, `Tooltip`
- [x] Hover / focus-visible / active / disabled states on every interactive surface
- [x] `EmptyState` refresh with an action slot
- [x] `Skeleton` loaders to replace bare spinners
- [x] Proper pluralisation helper (fixes **B3**)

### U2 — Real cancellation (backend, **B1**) ✅
- [x] Stream LLM responses (`stream=True`) so generation can be interrupted mid-flight
- [x] `CancellationToken` checked between agents and between sections
- [x] `POST /jobs/{id}/cancel` revokes the Celery task and signals the token
- [x] Workflow raises `JobCancelled`; job ends `cancelled`, KB marked, no partial publish
- [x] Tests: cancel mid-analysis and mid-composition actually stops LLM traffic

### U3 — Analysis and job view ✅
- [x] Replace the flat checklist with a **stage tree**: phase → agent → live sub-steps
- [x] Human-readable narration per stage, derived from step output, not agent names
- [x] Progress affordance: elapsed, current stage, "runs in the background — you can
      leave this page and come back"
- [x] Remove the log console from the default view (keep behind a "Technical details"
      disclosure for debugging)
- [x] Cancel button wired to real cancellation from U2

### U4 — Knowledge base card and doc-type picker ✅
- [x] KB card shows **what was found**: languages, top modules, route samples,
      dependency highlights, narrative topics — not just counts
- [x] Doc-type picker becomes rows with checkboxes, each with a real description of
      what that document contains and what evidence supports it
- [x] Fix nested-function symbol extraction (**B2**) so route-based suggestions are right
- [x] Re-check `suggest_doc_types` coverage once B2 lands

### U5 — Project creation and source ingestion (**B5**) ✅
- [x] Single dialog: name + description + first source
- [x] Validate the source **before** creating the project — clone/probe with progress
      ("Fetching repository…", "Reading 142 files…")
- [x] Only create the project once the source is confirmed, then navigate to it
- [x] Same flow for zip upload: accept, extract, verify, then create
- [x] Clear, specific errors (bad URL, private repo, unsupported archive)

### U6 — Documents: navigation, grouping, rendering ✅
- [x] Viewer becomes a single centred reading column (**remove the second pane**)
- [x] Replace `SimpleMarkdown` with a real renderer — tables, fenced code with
      highlighting, task lists, nested lists, blockquotes (**B4**)
- [x] Origin-aware back navigation (**B6**)
- [x] Documents page grouped by project, with counts and collapse
- [x] Document cards show doc type, size, generated-at, source job

### U7 — Cleanup ✅
- [x] Remove the templates tab from Settings (**B7**); keep the endpoint or drop it
- [x] Audit remaining pages (Dashboard, Projects list) against the principles above
- [x] Remove dead UI code left behind by earlier phases

## Non-goals

- Light mode — the studio stays dark-only.
- Non-Markdown output rendering (DOCX/MkDocs preview). Markdown first.
- Changing the analyse/compose backend architecture.
