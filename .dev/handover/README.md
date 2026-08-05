# UI Handover Pack

Prompts for handing the studio redesign to a specialised design/frontend agent.
Each file is a self-contained prompt — open it, copy the whole thing, paste it.

## Order

| # | File | Purpose | Run when |
|---|---|---|---|
| 1 | [01-first-screen.md](01-first-screen.md) | **Start here.** One screen only, so you can judge the direction in ~10 minutes before committing to a full redesign. Also asks the agent to declare the design tokens it invented, which everything else inherits. | First. Iterate here until you like it. |
| 2 | [02-product-brief.md](02-product-brief.md) | The whole product: what it does, the end-to-end workflow, every screen, every state, and what each screen has to communicate. No visual direction — that stays the agent's call. | After you approve the direction from #1. |
| 3 | [03-api-contract.md](03-api-contract.md) | Exact API layer — every endpoint, request/response shape, enum value, status string and polling behaviour. Reference material, not a prompt on its own. | Attach alongside #2 and #4. |
| 4 | [04-build-and-wire.md](04-build-and-wire.md) | Turning the approved design into working code in this repo: stack, file layout, conventions, wiring, acceptance checks. | Once the designs are approved. |

Prompt #1 is deliberately narrow. Everything after it assumes you liked something.

## What to attach

### With prompt 1 — first screen

Nothing is strictly required; it is a greenfield design task. Optional, only if you
want the agent anchored to something:

- A screenshot of the current landing page (`http://localhost:5173/`) — attach it as
  **"this is what we're replacing"**, and say so explicitly, or the agent will treat it
  as a style reference and stay close to it.
- 1–3 screenshots of products whose *feel* you like. This is the highest-signal thing
  you can provide, and it is worth more than any adjective. If you have none, skip it —
  the prompt is written to work without them.

**Do not attach** `ui/src/styles/theme.css` or any current component at this stage. It
is a dark-theme token set for the design being replaced, and it will anchor the agent
to what already exists.

### With prompt 2 — full product brief

Attach:

- **[03-api-contract.md](03-api-contract.md)** — always.
- The approved output from prompt 1 (the HTML file or the screenshot of it), as **"the
  approved direction — everything else must feel like this"**.
- **Screenshots of the current studio**, labelled *"current build, for content and data
  reference only — the visual design is being replaced"*. Capture these routes while
  logged in with at least one analysed project:

  | Route | Why it matters |
  |---|---|
  | `/app` | Dashboard — what we currently surface at a glance |
  | `/app/projects` | Project list rows |
  | `/app/projects/:id` | **The most important one.** Sources, knowledge-base evidence panel, the doc-type picker, jobs and documents all live here |
  | `/app/projects/:id/jobs/:jobId` | Live analysis progress — the stage tree mid-run, ideally captured while a job is actually running |
  | `/app/documents` | Documents grouped by project |
  | `/app/documents/:id` | The reading view, on a document with tables, code blocks and a Mermaid diagram |
  | `/app/settings` | LLM configuration |

  The job-in-progress screenshot is the one worth waiting for. It is the hardest screen
  in the product and the hardest to describe in words.

- **A real generated document** (`.md` export from `/app/documents/:id`) so the agent
  designs the reading view against genuine content — long headings, wide tables, 60+
  code blocks — rather than lorem ipsum.
- **A real `GET /projects/{id}/knowledge-base` response** as JSON. Run it against an
  analysed project and save the output. This drives the single richest screen in the
  app, and real values (module summaries, route paths, confidence scores) will change
  what the agent designs.

### With prompt 4 — build and wire

Attach:

- **[03-api-contract.md](03-api-contract.md)**
- The approved designs from prompt 2
- `CLAUDE.md` from the repo root — UI conventions, and the rule that the studio lives
  in `ui/` in this same repo

## Capturing the two JSON payloads

```bash
# log in
TOKEN=$(curl -s localhost:8001/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@docany.local","password":"admin1234"}' | jq -r .access_token)

# the knowledge-base payload (replace 1 with a project that has been analysed)
curl -s localhost:8001/api/v1/projects/1/knowledge-base \
  -H "authorization: Bearer $TOKEN" | jq > kb-sample.json

# a finished job, including its steps and their output_json
curl -s localhost:8001/api/v1/jobs/1 -H "authorization: Bearer $TOKEN" | jq > job-sample.json
```

Attach `job-sample.json` too if you have it — it shows the agent exactly what
`output_json` contains per stage, which is what the progress narration is built from.

## Things to tell the agent yourself

The prompts cover the product. These are your calls and are stated as constraints in
prompt 1 — change them there if you change your mind:

- **Light theme first**, orange accent. Dark comes later, so tokens must be built to
  support it even though only light ships now.
- Open-source project, not a commercial product. No pricing, no enterprise CTAs, no
  invented testimonials or customer logos.
- Runs fully offline against a local model. That is a genuine selling point and the
  landing page should say so.
