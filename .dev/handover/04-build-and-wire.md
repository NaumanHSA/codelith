> **How to use:** paste this whole file once the designs are approved. Attach
> [03-api-contract.md](03-api-contract.md), the approved designs, and the repo's
> `CLAUDE.md`.

---

# Build the redesigned studio and wire it to the backend

The designs are approved. Build them for real, in this repository, against the live API.

## Where it lives

The studio is **`ui/` inside the backend repo** — one repo, not two. There is no separate
frontend repository; anything you find describing one is out of date.

```
ui/
  index.html
  vite.config.ts
  src/
    styles/theme.css              design tokens
    app/
      App.tsx                     routes
      lib/        api.ts · types.ts · format.ts · narrate.ts · docTypes.ts
      components/ layout · shared · projects · jobs · knowledge · documents · ui
      pages/      LandingPage · auth/* · app/*
```

Run it with `cd ui && npm install && npm run dev` (port 5173). The API is at `:8000` by
default; this machine runs it on `:8001`.

## Current stack

React 18 · Vite 6 · Tailwind 4 · react-router 7 · Radix primitives · lucide-react ·
`motion` · sonner · react-markdown + remark-gfm + rehype-highlight + highlight.js.

Keep **React + Vite + TypeScript** — the Makefile, Docker build and CI expect them.
Everything above that line is yours to keep, replace or delete. The dependency list has
accumulated a lot that nothing imports (MUI, carousels, drag-and-drop, confetti,
masonry); prune what you do not use rather than building around it.

## Hard constraints

- **Fully offline.** No CDN scripts, no Google Fonts, no remote images, no analytics, no
  telemetry. The project's headline claim is that nothing leaves the user's machine, and
  the frontend must not quietly break it. Bundle or inline every asset.
- **Light theme ships; dark comes later.** Define tokens so a `dark` variant can be
  added without touching components. Note that `ui/index.html` currently hardcodes
  `class="dark"` on `<html>` — remove it.
- **All colour through tokens** in `ui/src/styles/theme.css`. No hardcoded Tailwind
  colours (`bg-white`, `text-slate-600`) in components.
- **All HTTP through one client** (`ui/src/app/lib/api.ts`): it attaches the JWT,
  refreshes once on `401`, retries, and only then redirects to sign-in.
- **API base URL from `VITE_API_URL`** (`ui/.env.local`), defaulting to `:8000`. Never
  hardcode a host or port.
- **IDs are integers.** Type them as `number`. A previous build typed them as `string`,
  called `.slice()` on one, and blanked the entire app — so also keep a route-level
  error boundary that fails to a readable screen instead of a white page.
- `prefers-reduced-motion` is honoured everywhere.

## Worth carrying over rather than reinventing

These solve problems that took real effort to find. Read them before replacing them:

| File | Why |
|---|---|
| `lib/narrate.ts` | Maps each agent + its `output_json` to human copy — *"Mapped 45 modules and found 77 facts"*. The copy is tuned; reuse the table even if you rebuild the component |
| `lib/docTypes.ts` | What each document type actually contains, for the picker |
| `lib/format.ts` | `pluralize`, `countLabel`, `formatDuration`, `humanize` with an acronym set — the old UI rendered "43 Dependencys" and "24 Env Vars" without them |
| `components/projects/NewProjectDialog.tsx` | The probe-before-create flow. The previous version created the project first and swallowed source errors |

## Behaviour the UI must get right

- **Polling.** `GET /jobs/{id}` every 2–3s while a job is not terminal. Stop on
  `completed` / `failed` / `cancelled` / `awaiting_review`. Do not leave intervals
  running after unmount, and do not poll a finished job.
- **The SSE log stream is secondary.** It carries logs, not step status, gives up after
  10 minutes, and a long composition can outlive it. Poll the job regardless;
  reconnect the stream on timeout if it is open.
- **Steps arrive incrementally.** A job three stages into seven returns three steps. The
  expected stage list per `job_type` is in the API contract — render queued stages from
  it, and render never-ran stages on a cancelled job as skipped rather than pending.
- **Cancel is real** and must be reachable within one click of anything long-running.
  Reflect the returned status; never optimistically claim "cancelled".
- **A running job must be visible from anywhere.** Users navigate away mid-analysis and
  need their way back.
- **`GET /projects/{id}/knowledge-base` returning `null`** is the "never analysed" signal,
  not an error.
- **Markdown is heavy.** Code-split the renderer (`React.lazy`) so it loads only when a
  document is opened — it is ~350 kB and the main bundle should stay near 450 kB.
- **Document origin.** A document opened from a project returns to that project, from a
  job returns to that job, from the global list returns to the list.

## Order of work

Ship in slices that can each be reviewed running, not one big-bang merge:

1. **Tokens + shell** — `theme.css` in light, primitives, navigation, error boundary,
   loading skeletons. Nothing else moves until this is right.
2. **Auth + landing** — the approved front door, sign-in, register, token persistence and
   refresh.
3. **Projects** — list, create (probe-first), detail before analysis.
4. **Analysis + job progress** — the stage view, polling, cancel, the running-job
   indicator in the shell.
5. **Knowledge base + doc-type picker + compose.**
6. **Documents** — list, reader, export, publish.
7. **Settings**, then prune unused dependencies and dead components.

## Definition of done

- `npm run build` succeeds with no TypeScript errors.
- **Zero console errors or warnings** during a full end-to-end run: sign in → create
  project from a real GitHub URL → analyse → wait for the knowledge base → compose →
  read the document.
- Cancel during analysis stops the job **and** stops the local model generating (watch
  LM Studio's log — if tokens keep streaming, it is not wired up).
- The document reader renders a real generated API reference with its tables, code
  blocks and Mermaid diagrams intact, with no raw `|---|` on screen.
- Every list, panel and detail screen has a designed empty, loading and error state.
- No hardcoded colours outside `theme.css`; no hardcoded API host; no network request to
  any origin other than the API.
- Keyboard: every interactive element reachable and visibly focused; dialogs trap focus
  and close on Escape.

## Backend gaps to design around, not paper over

- **PDF export does not exist.** Do not offer it.
- **`/documents/{id}/export` only implements Markdown.** DOCX, MkDocs and Docusaurus come
  from a generation job's `output_formats`.
- **Human review cannot resume.** A job that reaches `awaiting_review` ends there;
  approval does not restart composition. Show the state truthfully.
- **`/settings/templates` is read by nothing.** No UI for it.

If you hit anything else where the API cannot support the design, say so rather than
faking it in the frontend — the backend can change.
