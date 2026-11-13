# HTTP API

FastAPI, mounted at `/api/v1`. Around 90 routes.

!!! tip "The full list is served by the app itself"
    Start Codelith and open **<http://localhost:8000/docs>**. That is generated from the
    code, so it cannot go stale the way a hand-written list would. This page describes
    the *shape*, so you know where to look.

    Interactive docs are disabled when `APP_ENV=production`.

## Shape

Routes are thin: validate input, call a service, return a schema. Business logic lives
in `codelith/services/` and database access goes through `codelith/db/repositories/` —
never SQLAlchemy from a route.

| Group | Routes | What it covers |
|---|---|---|
| `projects` | 44 | Codebases, sources, analysis, the knowledge base, modules, files, evidence, chat, drift, composition, the documentation site |
| `settings` | 12 | Configured models, tier assignments, connection tests |
| `jobs` | 6 | Status, logs, cancellation |
| `documents` | 5 | Generated documents and exports |
| `publications` | 4 | Published documentation sites |
| `auth` | 4 | Sign in, refresh, OAuth |
| `organizations` | 3 | |
| root | 8 | `/health`, `/metrics`, published sites, the studio |

## The ones worth knowing

**`POST /api/v1/projects/with-source`** — create a codebase and attach its source in
one call. What the studio and `codelith analyse` both use.

**`POST /api/v1/projects/{id}/analyze`** — start a reading. Returns a job. Pass
`force` to rebuild a commit that already has one.

**`GET /api/v1/jobs/{id}`** — poll for progress. The SSE stream beside it carries logs
only and times out after ten minutes; **progress comes from polling**, not from the
stream.

**`GET /api/v1/projects/{id}/knowledge-base`** — what the reading found.

**`GET /api/v1/projects/{id}/modules`** — every module with its role, its summary, and
the component the architecture pass placed it in.

**`GET /api/v1/projects/{id}/files`** and **`/files/{path}`** — the file tree, and one
file [rebuilt from stored chunks](../how-it-works/chunks-and-retrieval.md#reading-a-file-back).
A path that was seen but kept nothing returns `indexed: false` rather than 404.

**`GET /api/v1/projects/{id}/preflight`** — what a change to a file or symbol would
touch. The HTTP form of [`before_edit`](../mcp.md#before_edit).

**`POST /api/v1/projects/{id}/reviews`** — review a change against the knowledge: send
one (`change`, as `codelith review` collects it from git) or, for a codebase read from a
folder on this machine, omit it to review the working copy. Kept, and listed by
**`GET /api/v1/projects/{id}/reviews`**; one in full at **`/reviews/{review_id}`**. The
HTTP form of [`review_changes`](../mcp.md#review_changes).

**`GET /api/v1/projects/{id}/flows`** — every way into the code (routes, commands,
scheduled jobs, entry points) with the length of its path; one in full, step by step,
with a diagram, at **`/flows/{flow_id}`**. The HTTP form of
[`trace_flow`](../mcp.md#trace_flow-and-how_to).

**`GET /api/v1/projects/{id}/agent-guide?format=agents|claude`** — the instruction file
for coding agents, and the house-style recipes it is made from. What
`codelith agents-md` writes.

**`GET /api/v1/agents/gaps`** — what agents asked over MCP and could not get. Admin only.

**`GET /api/v1/projects/{id}/hotspots`** — files that change often, that much depends
on, and that no test reaches, from the history kept with the reading.

**`GET /api/v1/projects/{id}/timeline`** — each kept reading's size, imports between
parts, and imports that run against the columns, oldest first.

**`GET /api/v1/projects/{id}/tour`** — the stops of a guided walk through the code; the
same as a document at **`/tour/markdown`**.

**`GET /api/v1/projects/{id}/readings`** — every finished reading, newest first, with
how many files each kept. **`POST /readings/{kb_id}/files`** fetches the files of a
reading taken before readings kept them, from git at its commit.

**`GET /api/v1/projects/{id}/compare?before=&after=`** — the files that changed between
two readings (the latest two by default), with lines added and removed, renames, and
each file's part, reach, tests and citing pages. One file, line by line, at
**`/compare/file?path=&old_path=`**.

**`/api/v1/projects/{id}/qa/...`** — QA: `GET catalog` (areas and depths), `POST runs`
(`{areas, depth, scope, online}`; runs on the worker), `GET runs`, `GET runs/{run}`,
`POST runs/{run}/cancel`, `GET runs/{run}/findings`, `GET findings/{finding}` (with the
code around it, secrets masked), `PUT findings/{fingerprint}/state`
(`{status: dismissed | accepted | open, reason}`).

**`GET /api/v1/projects/{id}/runbook`** — what the code needs, how to install, run and
test it, and the environment it reads against what its files declare. The same as
`how_to("run")` over MCP.

**`GET /api/v1/projects/{id}/drift`** — two readings compared: modules, facts, parts,
and the pages at risk.

**`POST /api/v1/projects/{id}/chat/stream`** — ask a question, streamed.

## Auth

JWT bearer tokens. Sign in at `POST /api/v1/auth/login`; the studio attaches the token,
refreshes once on a 401, retries, and only then bounces to sign-in.

Published documentation sites are the exception: they are mounted at the root, outside
`/api/v1`, and served without a session. The capability URL is the credential — the
people a site is shared with have no account and no idea what an API is.

## Conventions

- **IDs are integers.**
- An unknown path under `/api/v1` returns a **JSON 404**, not the studio's HTML shell.
  The studio is mounted last, as a fallback, precisely so it cannot shadow the API.
- `/health` reports `status`, `env`, and whether the process is in a container — the
  browser cannot work that last one out, and it changes what a model endpoint should
  say.
