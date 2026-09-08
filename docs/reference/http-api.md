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

**`GET /api/v1/projects/{id}/drift`** — two readings compared.

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
