> **How to use:** reference material, not a prompt on its own. Attach it alongside
> [02-product-brief.md](02-product-brief.md) and [04-build-and-wire.md](04-build-and-wire.md).

---

# Document Anything — API contract

Every endpoint the studio uses, with exact request and response shapes. Generated from
the FastAPI routers and Pydantic v2 schemas; field names and types are literal.

- **Base URL**: `http://localhost:8000/api/v1` (this dev box runs it on `:8001` —
  configurable, so read it from an env var, never hardcode).
- **Format**: JSON in, JSON out. `datetime` is ISO-8601 with timezone.
- **IDs are integers**, not strings or UUIDs. Every `id` in this document is an `int`.
  (A previous frontend typed them as `string` and called `.slice()` on them, which blanked
  the app.)
- **Interactive docs**: `GET /docs` (Swagger), `GET /openapi.json`.

## Authentication

JWT bearer. Send `Authorization: Bearer <access_token>` on everything except
register/login/refresh.

Access tokens expire. On any `401`, call `/auth/refresh` with the stored refresh token,
retry the original request once, and only then bounce to sign-in. Persist both tokens
across reloads.

### Roles

`admin` · `manager` · `reviewer` · `viewer`

| Requirement | Applies to |
|---|---|
| any authenticated user | all reads |
| `manager` or `admin` | create/update/delete project, add/remove source, upload, probe, analyze, compose, create job, cancel |
| `reviewer` or above | approve a job |
| `admin` | settings |

A forbidden action returns `403`.

### Errors

```jsonc
// handled application errors
{ "error": "Project not found", "detail": { }  }
// FastAPI validation and HTTPException
{ "detail": "Source is not usable" }
// unhandled
{ "error": "Internal server error" }
```

Read `error` first, fall back to `detail`, and remember `detail` is sometimes an array of
validation objects rather than a string.

---

## Auth

### `POST /auth/register` → `201`

```jsonc
// request
{ "email": "you@example.com", "password": "at-least-8-chars", "full_name": "Ada" }
// response — a user, NOT tokens. Log in afterwards.
{ "id": 1, "email": "you@example.com", "full_name": "Ada",
  "role": "manager", "org_id": 1, "is_active": true }
```

### `POST /auth/login` → `200`

```jsonc
// request
{ "email": "you@example.com", "password": "…" }
// response
{ "access_token": "eyJ…", "refresh_token": "eyJ…", "token_type": "bearer" }
```

### `POST /auth/refresh` → `200`

```jsonc
{ "refresh_token": "eyJ…" }   // → same shape as login
```

### `GET /auth/me` → `200`

Returns the `UserOut` shape above.

---

## Projects

### `GET /projects?limit=50&offset=0` → `200`

Array of `ProjectOut`:

```jsonc
{
  "id": 1,
  "org_id": 1,
  "name": "neurosurfer",
  "slug": "neurosurfer",
  "description": "Chat server",
  "status": "active",
  "created_at": "2026-08-04T10:12:33.114Z",
  "updated_at": "2026-08-05T09:01:02.552Z",
  "sources": [ /* ProjectSourceOut */ ],
  "stats": { "source_count": 1, "job_count": 3, "doc_count": 2 },
  "latest_job": { "id": 42, "status": "completed" }   // or null
}
```

`stats` and `latest_job` may be `null`.

### `GET /projects/{id}` → `200`
Single `ProjectOut`.

### `POST /projects` → `201`

```jsonc
{ "name": "My project", "description": "optional", "sources": [] }
```

Prefer `/projects/with-source` below — this one can leave a project with no source.

### `PATCH /projects/{id}` → `200`

```jsonc
{ "name": "…", "description": "…", "status": "…" }   // all optional
```

### `DELETE /projects/{id}` → `204`

---

## Sources

### `POST /projects/sources:probe` → `200`

**Fetches and inspects a source without creating anything.** This is what powers the
"checking the repository…" step in project creation. It clones, so it takes seconds —
show progress.

```jsonc
// request
{ "source_type": "github", "url_or_path": "https://github.com/org/repo", "branch": null }
```

`source_type`: `"github"` · `"gitlab"` · `"bitbucket"` · `"local"`

```jsonc
// response — note ok:false is still HTTP 200
{
  "ok": true,
  "source_type": "github",
  "url_or_path": "https://github.com/org/repo",
  "resolved_path": "/tmp/repos/repo",
  "branch": "main",
  "commit_sha": "8f3c1d2…",
  "file_count": 142,
  "analysable_files": 170,
  "languages": { "python": 170, "markdown": 22, "yaml": 5 },
  "error": null
}
```

On failure: `"ok": false` with a human-written `error` — *"Repository not found. Check
the URL and that it is public."*, *"Branch 'develop' does not exist."*, *"Nothing here we
can analyse."* Show `error` directly; it is written for users.

### `POST /projects/with-source` → `201`

Creates a project **and** its first source atomically. Probes first; on failure returns
`422` and writes nothing.

```jsonc
{
  "name": "My project",
  "description": "optional",
  "source_type": "github",
  "url_or_path": "https://github.com/org/repo",
  "branch": null,
  "config_json": null
}
```

Returns the full `ProjectOut`.

### `POST /projects/{id}/sources` → `201`

```jsonc
{ "source_type": "github", "url_or_path": "…", "branch": null, "config_json": {} }
```

```jsonc
// ProjectSourceOut
{ "id": 7, "project_id": 1, "source_type": "github",
  "url_or_path": "https://github.com/org/repo", "branch": "main",
  "config_json": { "probe": { "file_count": 142, "analysable_files": 170,
                              "languages": {…}, "commit_sha": "8f3c…" } },
  "created_at": "2026-08-04T10:12:33Z" }
```

### `DELETE /projects/{id}/sources/{source_id}` → `204`

### `POST /projects/{id}/upload` → `201`

`multipart/form-data`, field name `file`. A `.zip` is extracted; a single file is stored
as-is. Returns `ProjectSourceOut`.

Allowed extensions: `.zip` · `.py .js .ts .jsx .tsx .go .rs .java .kt .swift .c .cpp .h
.cs .rb .php .scala .sh .bash` · `.toml .yaml .yml .json .xml .env .ini .cfg` ·
`.md .mdx .txt .rst .pdf` · `.html .css`

Anything else → `400` with the allowed list in `detail`.

---

## Phase 1 — Analyse

### `POST /projects/{id}/analyze` → `202`

```jsonc
{ "force": false }   // true re-analyses even if a ready KB exists for this commit
```

Deliberately takes **no document type**. Returns a `JobOut` with
`job_type: "analysis"` — poll it.

### `GET /projects/{id}/knowledge-base` → `200`

**Returns `null` when the project has never been analysed** — that is the signal to show
the analyse call-to-action rather than a picker. Otherwise the single richest payload in
the API:

```jsonc
{
  "knowledge_base": {
    "id": 12,
    "project_id": 1,
    "job_id": 42,
    "commit_sha": "8f3c1d2e…",
    "status": "ready",
    "schema_version": 1,
    "stats": { "modules": 30, "entities": 77, "chunks": 1204 },
    "error_message": null,
    "created_at": "2026-08-05T08:00:00Z",
    "completed_at": "2026-08-05T08:02:52Z"
  },
  "module_count": 30,
  "entity_count": 77,
  "narrative_topics": ["overview", "architecture", "request_lifecycle", "auth", "configuration"],
  "languages": ["python"],
  "roles": { "api": 4, "service": 9, "data_access": 3, "model": 2, "utility": 6, "test": 6 },
  "entity_kinds": { "route": 28, "dependency": 46, "env_var": 24, "entrypoint": 3 },

  "suggested_doc_types": [
    { "doc_type": "api",             "confidence": 0.95, "reason": "28 HTTP routes detected" },
    { "doc_type": "architecture",    "confidence": 0.90, "reason": "30 modules mapped across the codebase" },
    { "doc_type": "getting_started", "confidence": 0.70, "reason": "3 entrypoints and 46 declared dependencies" },
    { "doc_type": "modules",         "confidence": 0.60, "reason": "several service and utility modules worth documenting individually" }
  ],

  "top_modules": [
    { "path": "app/services", "name": "services", "role": "service", "loc": 2140,
      "summary": "Business logic for projects, jobs and documents. Each service owns one aggregate and is the only place routes are allowed to reach the repositories from…" }
  ],
  "sample_routes": [
    { "kind": "route", "name": "POST /api/v1/projects/{id}/analyze", "detail": "app/api/v1/projects.py:132" }
  ],
  "key_dependencies": ["fastapi", "sqlalchemy", "celery", "langgraph", "openai"],
  "entrypoints": ["app/main.py", "app/workers/celery_app.py"]
}
```

`status` (`KBStatus`): `pending` · `running` · `ready` · `degraded` · `failed` · `stale`
— `ready` and `degraded` are both usable for composition; `degraded` means a stage
failed and should carry a warning.

`role` (`ModuleRole`): `api` · `service` · `data_access` · `model` · `schema` · `worker`
· `ui` · `cli` · `config` · `infra` · `test` · `utility` · `unknown`

`kind` (`EntityKind`): `route` · `entrypoint` · `service` · `dependency` · `env_var` ·
`config_file` · `datastore` · `external_api` · `cli_command` · `scheduled_task` ·
`event` · `infra_resource` · `test_suite`

`narrative_topics` (`NarrativeTopic`): `overview` · `architecture` · `request_lifecycle`
· `data_model` · `auth` · `configuration` · `deployment` · `testing` · `error_handling`
· `integrations`

Treat every list as possibly empty and every enum as possibly containing a value you do
not recognise — render unknowns readably rather than crashing.

---

## Phase 2 — Compose

### `POST /projects/{id}/compose` → `202`

```jsonc
{
  "doc_types": ["architecture", "api"],     // min 1
  "output_formats": ["markdown"],
  "human_review": false,
  "kb_id": null                             // defaults to the latest usable KB
}
```

`doc_types`: `architecture` · `api` · `getting_started` · `deployment` · `modules`
(the picker should offer whatever `suggested_doc_types` returned).

`output_formats`: `markdown` · `docx` · `mkdocs` · `docusaurus`.
**`pdf` is not implemented** — do not offer it.

Returns a `JobOut` with `job_type: "composition"`.

### `POST /projects/{id}/jobs` → `201` *(legacy)*

Single-shot analyse-and-write. Kept for older clients — **do not build new UI on it.**

```jsonc
{ "config": { "doc_types": ["architecture"], "output_formats": ["markdown"],
              "include_diagrams": true, "human_review": false, "llm_model": null } }
```

---

## Jobs

### `GET /projects/{id}/jobs?limit=50&offset=0` → `200`
Array of `JobOut`.

### `GET /jobs/{id}` → `200`

```jsonc
{
  "id": 42,
  "project_id": 1,
  "job_type": "analysis",              // "analysis" | "composition"
  "status": "running",
  "config_json": { "doc_types": ["architecture"], "output_formats": ["markdown"], "human_review": false },
  "doc_types": ["architecture"],       // derived from config_json
  "output_formats": ["markdown"],      // derived
  "requires_human_review": false,      // derived
  "error_message": null,
  "started_at": "2026-08-05T08:00:00Z",
  "completed_at": null,
  "created_at": "2026-08-05T07:59:58Z",
  "steps": [
    {
      "id": 301,
      "name": "structured_extractor_agent",   // serialized from agent_name
      "status": "completed",
      "started_at": "2026-08-05T08:00:12Z",
      "completed_at": "2026-08-05T08:00:41Z",
      "duration_seconds": 29.4,
      "output_json": { "modules": 30, "entities": 77 }
    }
  ]
}
```

**Job `status`**: `pending` · `running` · `awaiting_review` · `completed` · `failed` ·
`cancelled`
**Step `status`**: `pending` · `running` · `completed` · `failed`

Steps appear as they start — a job that has run three of seven stages has three entries,
so the UI must know the expected stage list in advance to show what is still queued.

#### Expected stages, in order

```
analysis      repo_analyzer_agent · structured_extractor_agent · semantic_indexer_agent ·
              module_summarizer_agent · architecture_synthesizer_agent ·
              narrative_writer_agent · kb_persister_agent

composition   kb_loader_agent · composition_strategy_agent · composition_planner_agent ·
              composition_writer_agent · diagram_agent ‖ qa_agent · gate ·
              formatter_agent · publisher_agent
```

`diagram_agent` and `qa_agent` run in parallel; `gate` is a no-op join.

#### `output_json` per stage

This is what turns a progress bar into a report. Keys, by agent:

| Agent | Keys |
|---|---|
| `repo_analyzer` | `total_files`, `sources_processed` |
| `structured_extractor` | `modules`, `entities` |
| `semantic_indexer` | `chunks`, `embed_failures` |
| `module_summarizer` | `summarised`, `failed` |
| `architecture_synthesizer` | `services`, `degraded` |
| `narrative_writer` | `written`, `skipped` |
| `kb_persister` | `status` |
| `kb_loader` | `doc_types` |
| `composition_planner` | `sections` |
| `composition_writer` | `doc_count` |
| `diagram` | `diagrams`, `skipped` |
| `qa` | `all_approved` |
| `formatter` | `formats` |
| `publisher` | `saved_doc_ids` |

Every key is optional — treat a missing one as "not reported", never as zero.

### `GET /jobs/{id}/logs` → `200`

```jsonc
[ { "id": 9001, "agent": "module_summarizer_agent", "level": "info",
    "message": "Summarised 30 modules", "timestamp": "2026-08-05T08:01:02Z", "extra": {} } ]
```

`level`: `debug` · `info` · `warning` · `error`

### `GET /jobs/{id}/stream` — Server-Sent Events

Live log stream. `EventSource` cannot set headers, so pass the JWT as a query
parameter: `/api/v1/jobs/42/stream?token=<access_token>`.

```
data: {"id":9001,"agent":"…","level":"info","message":"…","timestamp":"…","extra":{}}

event: done
data: {"status":"completed"}

event: error
data: {"detail":"Job not found"}

event: timeout
data: {}
```

It polls once per second and gives up after 10 minutes (`event: timeout`) — a long
composition can outlive the stream, so **reconnect on timeout and keep polling
`GET /jobs/{id}` regardless**. The stream carries logs; it does not carry step status.
Poll the job every 2–3s for stage progress.

### `POST /jobs/{id}/cancel` → `200`

No body. Returns the updated `JobOut`. This is real: it signals a Redis cancellation
token, revokes the Celery task and aborts the in-flight LLM stream. The job ends
`cancelled`, not `failed`; stages that never ran stay `pending` and should render as
skipped rather than queued.

### `POST /jobs/{id}/approve` → `200`

```jsonc
{ "approved": true, "comment": "optional" }
```

Only relevant when `status == "awaiting_review"`. **Known backend limitation:** the graph
routes to `END` with no checkpointer, so approval cannot currently resume composition.
Surface the state honestly; do not build a workflow that implies resumption works.

---

## Documents

### `GET /documents?project_id=1&limit=50&offset=0` → `200`

`project_id` is optional — omit it for every document across every project.

```jsonc
{
  "id": 88,
  "project_id": 1,
  "job_id": 42,
  "doc_type": "architecture",
  "title": "Architecture Guide",
  "content_markdown": "# Architecture\n\n…",
  "storage_path": "documents/1/88/document.md",
  "version": 1,
  "status": "draft",
  "created_at": "2026-08-05T08:09:31Z"
}
```

`status`: `draft` · `review` · `published`

**`content_markdown` is the full document — 15k–40k characters.** The list endpoint
returns it for every row, so do not rely on the list for cheap counts; render from it
lazily.

### `GET /documents/{id}` → `200`
Single document, same shape.

### `PATCH /documents/{id}` → `200`

```jsonc
{ "title": "…", "content_markdown": "…" }   // both optional
```

### `POST /documents/{id}/publish` → `200`
Returns the updated document.

### `GET /documents/{id}/export?format=markdown` → `202`

```jsonc
{ "url": "/api/v1/documents/88/export/status?format=markdown" }
```

**Only `markdown` is implemented here**; anything else raises server-side. DOCX, MkDocs
and Docusaurus are produced by a *generation job*'s `output_formats`, not by this
endpoint. The returned polling URL does not exist yet either — treat export as
Markdown-download-only for now and do not design a rich export flow around it.

---

## Settings *(admin only)*

### `GET` / `PUT /settings/llm`

```jsonc
{
  "base_url": "http://localhost:1234/v1",
  "api_key": "lm-studio",
  "default_model": "local-model",
  "quality_model": "qwen/qwen3.5-9b",
  "fast_model": "liquid/lfm2.5-1.2b",
  "temperature": 0.2,
  "max_tokens": 4096,
  "max_react_iterations": 20
}
```

Two model slots because tasks are tiered: `fast_model` handles classification,
extraction, summarisation and diagrams; `quality_model` handles planning, writing,
review and architecture. Both may name the same model.

`/settings/templates` also exists but **nothing in the backend reads it** — do not build
UI for it.

---

## Rendering documents

`content_markdown` is GitHub-flavoured Markdown and needs, at minimum:

- **tables** — a real API reference contains 25+ of them, some very wide
- **fenced code with syntax highlighting** — 60+ blocks, mixed languages
- **Mermaid diagrams** in ```mermaid fences
- headings (used for navigation), nested lists, task lists, blockquotes, inline code,
  links

Everything must be bundled — no CDN, no remote fonts, no network at render time. The
Markdown stack is heavy (~350 kB); code-split it so it only loads when a document is
opened.

---

## A complete flow

```
POST /auth/login                              → tokens
POST /projects/sources:probe                  → { ok: true, file_count: 142, … }
POST /projects/with-source                    → project { id: 1 }
POST /projects/1/analyze                      → job  { id: 42, job_type: "analysis" }
GET  /jobs/42          (poll ~2s)             → steps fill in, status → "completed"
GET  /projects/1/knowledge-base               → evidence + suggested_doc_types
POST /projects/1/compose  { doc_types:[…] }   → job { id: 43, job_type: "composition" }
GET  /jobs/43          (poll ~2s)             → status → "completed"
GET  /documents?project_id=1                  → the finished documents
```
