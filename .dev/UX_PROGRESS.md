# UX Overhaul Progress

Execution tracker for [UX_PLAN.md](UX_PLAN.md).

Legend: ⬜ not started · 🟨 in progress · ✅ done · ⛔ blocked · ⏭️ deferred

## Summary

| Phase | Scope | Status |
|---|---|---|
| U1 | Design system foundation | ✅ |
| U2 | Real cancellation (backend) | ✅ |
| U3 | Analysis and job view | ✅ |
| U4 | Knowledge base card and doc-type picker | ✅ |
| U5 | Project creation and source ingestion | ✅ |
| U6 | Documents: navigation, grouping, rendering | ✅ |
| U7 | Cleanup | ✅ |

## Verified root causes

Established before planning, so the phases fix causes rather than symptoms.

| # | Finding | Evidence |
|---|---|---|
| B1 | Cancel is cosmetic | `JobService.cancel()` sets `status='cancelled'` and commits. `celery_task_id` is stored but never used — no `revoke()`, no abort. The worker keeps streaming from LM Studio |
| B2 | Nested routes invisible | neurosurfer source has 28 `@router.<verb>(` decorators; KB has **0** route entities. `PythonProvider._walk` recurses into `ClassDef` only, and neurosurfer registers routes inside `mount_chat_routes()`. Verified: `extract_symbols` returns 0 decorated symbols for `routes_chat.py` |
| B3 | "Dependencys" | `{count} {humanize(kind)}{count === 1 ? '' : 's'}` |
| B4 | Tables render raw | `SimpleMarkdown` handles headings/lists/code/quotes only — no table branch |
| B5 | Project created before source validation | `AddSourceModal` posts the project first, then the source |
| B6 | Back goes to all documents | Viewer hardcodes `/app/documents` |
| B7 | Templates unused | No agent, workflow or service reads `system_settings` templates — write-only from the UI |

## Phase log

### U1 — Design system foundation ✅ (2026-08-05)

- `theme.css`: interaction surfaces (`--surface-hover/active/raised`, `--border-hover`),
  an elevation scale, motion tokens (one easing, three speeds), a single
  `:focus-visible` treatment, and a `prefers-reduced-motion` guard.
- `components/shared/Interactive.tsx`: `Row`, `ClickableCard`, `IconButton`,
  `Skeleton`, `SkeletonRows`.
- `Row`/`ClickableCard` render a real `<a>`, so middle-click and cmd-click still open
  a new tab while the whole surface responds to hover/focus/press. `IconButton` stops
  propagation so per-row actions do not trigger the row's navigation.
- `pluralize()` / `countLabel()` — fixes **B3** ("43 Dependencys").

### U2 — Real cancellation ✅ (2026-08-05)

Fixes **B1**. Cancelling now stops work rather than relabelling it.

- `app/core/cancellation.py`: `CancellationToken` (Redis-backed, so the signal crosses
  the API→worker process boundary), `JobCancelled`, and an ambient token so agents can
  check without threading it through every signature.
- `chat_completion` streams by default (`LLM_STREAMING`). Not for latency — for
  interruptibility. A non-streamed call is one opaque await with no moment to abandon
  it; streaming lets us check the token between chunks and `close()` the stream, which
  is what actually stops the model generating.
- `JobService.cancel()` signals the token, revokes the Celery task
  (`terminate=False`, so the worker unwinds cleanly), then records the status.
- Checks between graph stages, before each section's retrieval, and before each queued
  section starts.
- `JobCancelled` ends analysis/composition as **cancelled**, not failed. A half-built
  KB is marked; a half-written document is never published.

Two holes found while wiring it, both of which would have silently defeated cancellation:

1. **The fan-out agents would have swallowed it.** They catch broad `Exception` and use
   `gather(return_exceptions=True)`, so a cancellation looked like "that section
   failed" and the job carried on writing the rest.
2. **Tenacity would have retried it.** `_chat_with_retry` retried on `Exception`, and
   `JobCancelled` is one — so cancelling would have triggered three more LLM calls with
   exponential backoff. Now excluded via `retry_if_not_exception_type`.

10 tests, asserting on *work stopping* rather than status text — including one proving
a cancelled stream aborts after fewer than 5 chunks instead of draining all 100, and
one proving the retry decorator issues exactly one call.

### U3 — Analysis and job view ✅ (2026-08-05)

- `StageTree` replaces the flat checklist: a connected rail, plain-language stage
  names, and — the part that matters — each completed stage reports **what it
  produced**, derived from the step's recorded `output_json`. "Mapping the structure"
  becomes *"Mapped 45 modules and found 77 facts"*.
- While a stage is pending or running it explains its own purpose, so a waiting user
  knows what is being done for them.
- The log console moved behind a collapsed "Technical details" disclosure. It is
  debug output; it was the main thing on screen.
- A running job now says plainly that it continues in the background and the page can
  be left. Elapsed time ticks live.
- Stages that never ran (cancelled/failed job) render as skipped rather than pretending
  to still be queued.

### U4 — Knowledge base card and doc-type picker ✅ (2026-08-05)

Fixes **B2** and **B3**.

- `PythonProvider._walk` now recurses into function bodies. A very common FastAPI
  layout registers routes inside a setup function, which made them invisible:
  neurosurfer went from **0 routes to all 28**, and now correctly suggests
  **API Reference at 95%**. Function *locals* are still skipped so the KB is not
  flooded with noise. Three regression tests.
- The card shows evidence, not counters: largest modules with their real summaries and
  LOC, actual endpoint paths, dependency names, understood topics — behind a
  "Show what we found" disclosure.
- The picker is rows with checkboxes. Each says what the document contains
  ("Routes, authentication, request/response shapes, error handling"), roughly how long
  it takes, the confidence, and the evidence behind the suggestion.

### U5 — Project creation and source ingestion ✅ (2026-08-05)

Fixes **B5**. The old flow called `apiPost('/projects')` then
`submitSource(...).catch(() => {})` — it created the project first and **silently
swallowed source failures**.

- `SourceService.probe()` fetches and inspects a source without touching the database,
  and translates clone failures into something actionable ("Repository not found.
  Check the URL and that it is public."). It also rejects a repo that fetched fine but
  contains no analysable files, rather than letting analysis build an empty KB.
- `POST /projects/sources:probe` and `POST /projects/with-source` (422 + nothing
  created on failure).
- One dialog for name, description and first source, with live feedback
  ("Fetching repository…" → "142 files fetched · 170 we can analyse · python").
  The project name is suggested from the repo slug.
- Deleted the dead `CreateProjectModal` (123 lines) so the swallow-errors bug cannot
  be resurrected.

### U6 — Documents ✅ (2026-08-05)

Fixes **B4** and **B6**.

- `react-markdown` + `remark-gfm` + `rehype-highlight` replace the hand-rolled parser.
  Verified on a real generated API reference: **25 tables, 62 rows, 59 code blocks,
  zero raw `|---` left on screen**. Syntax highlighting uses a small hand-written
  highlight.js theme so code shares the studio palette.
- The viewer is a single centred reading column; the second pane is gone and secondary
  actions live in a sticky header.
- Origin-aware back navigation via `?from=/?project=/?job=` — opening a document from a
  project returns to that project, not the global list.
- The Documents page groups by project, collapsible, with search across title, type and
  project name. Rows are whole-row targets and carry type, status and word count.
- The markdown stack is code-split (`React.lazy`): it is 347 kB and only loads when a
  document is opened, so the main bundle stayed at ~455 kB.

### U7 — Cleanup ✅ (2026-08-05)

Fixes **B7**. Removed the Doc Templates tab and the 88-line `TemplatesTab` — nothing in
the backend ever read `system_settings` templates.
