# API Reference — document-anything

**Base URL**: `http://localhost:8000` (dev) — set via `NEXT_PUBLIC_API_URL` env var  
**Auth header**: `Authorization: Bearer <access_token>` on all authenticated routes  
**Content-Type**: `application/json` for all request bodies  
**Interactive docs**: `http://localhost:8000/docs` (FastAPI Swagger UI)

---

## Authentication

### Register
```
POST /api/v1/auth/register
Body: {
  "email": "user@example.com",
  "password": "secretpass",
  "full_name": "Jane Smith"
}
Response 201: {
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
Errors: 409 — email already registered
```

### Login
```
POST /api/v1/auth/login
Body: { "email": "...", "password": "..." }
Response 200: { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
Errors: 401 — invalid credentials
```

### Refresh Token
```
POST /api/v1/auth/refresh
Body: { "refresh_token": "eyJ..." }
Response 200: { "access_token": "..." }
Errors: 401 — refresh token expired or invalid
```

### Get Current User
```
GET /api/v1/auth/me
Auth: required
Response 200: {
  "id": 1,
  "email": "user@example.com",
  "full_name": "Jane Smith",
  "role": "admin",           ← "admin" | "manager" | "reviewer" | "user"
  "is_active": true,
  "created_at": "2025-01-01T00:00:00Z"
}
```

---

## Organizations

### List Organizations
```
GET /api/v1/organizations
Auth: required
Response 200: [{ "id": 1, "name": "Acme Corp", "slug": "acme", "created_at": "..." }]
```

### Create Organization
```
POST /api/v1/organizations
Auth: required (admin)
Body: { "name": "Acme Corp", "slug": "acme" }
Response 201: { "id": 1, "name": "Acme Corp", "slug": "acme", ... }
```

### Get Organization
```
GET /api/v1/organizations/{org_id}
Auth: required
Response 200: { "id": 1, "name": "...", "slug": "...", "created_at": "..." }
```

### Update Organization
```
PATCH /api/v1/organizations/{org_id}
Auth: required (admin/manager)
Body: { "name": "New Name" }
Response 200: { updated organization object }
```

### Delete Organization
```
DELETE /api/v1/organizations/{org_id}
Auth: required (admin)
Response 204: no content
```

---

## Projects

### List Projects
```
GET /api/v1/projects?limit=50&offset=0
Auth: required
Response 200: [
  {
    "id": 1,
    "name": "My API Project",
    "description": "FastAPI backend docs",
    "org_id": 1,
    "created_at": "...",
    "sources": [
      {
        "id": 1,
        "source_type": "github",    ← "github" | "gitlab" | "bitbucket" | "local"
        "url_or_path": "https://github.com/owner/repo",
        "branch": "main",
        "config_json": {}
      }
    ]
  }
]
```

### Create Project
```
POST /api/v1/projects
Auth: required (admin/manager)
Body: { "name": "My API Project", "description": "optional" }
Response 201: { project object }
```

### Get Project
```
GET /api/v1/projects/{project_id}
Auth: required
Response 200: { full project object including sources }
```

### Update Project
```
PATCH /api/v1/projects/{project_id}
Auth: required (admin/manager)
Body: { "name": "...", "description": "..." }   ← all fields optional
Response 200: { updated project object }
```

### Delete Project
```
DELETE /api/v1/projects/{project_id}
Auth: required (admin/manager)
Response 204: no content
```

### Add Source to Project
```
POST /api/v1/projects/{project_id}/sources
Auth: required (admin/manager)
Body: {
  "source_type": "github",          ← required: "github" | "gitlab" | "bitbucket" | "local"
  "url_or_path": "https://github.com/owner/repo",   ← required
  "branch": "main",                 ← optional, default "main"
  "config_json": { "token": "..." } ← optional, for private repos
}
Response 201: {
  "id": 5,
  "project_id": 1,
  "source_type": "github",
  "url_or_path": "...",
  "branch": "main",
  "config_json": {},
  "created_at": "..."
}
```

---

## Jobs

### Create Job (Start Documentation Generation)
```
POST /api/v1/projects/{project_id}/jobs
Auth: required (admin/manager)
Body: {
  "config": {
    "doc_types": ["architecture", "api", "modules", "getting_started"],
    "output_formats": ["markdown", "docx"],
    "requires_human_review": false
  }
}
Response 201: {
  "id": 42,
  "project_id": 1,
  "status": "pending",              ← immediately starts Celery task
  "config_json": { ... },
  "celery_task_id": "abc-123",
  "created_at": "...",
  "started_at": null,
  "completed_at": null,
  "error_message": null,
  "steps": []
}
```

**Valid doc_types**: `architecture`, `api`, `modules`, `getting_started`, `deployment`, `contributing`, `changelog`  
**Valid output_formats**: `markdown`, `docx`, `mkdocs`, `docusaurus`

### Get Job
```
GET /api/v1/jobs/{job_id}
Auth: required
Response 200: {
  "id": 42,
  "project_id": 1,
  "status": "running",        ← "pending" | "running" | "awaiting_review" | "completed" | "failed" | "cancelled"
  "config_json": {
    "doc_types": ["architecture", "api"],
    "output_formats": ["markdown"],
    "requires_human_review": false
  },
  "celery_task_id": "...",
  "error_message": null,
  "created_at": "...",
  "started_at": "...",
  "completed_at": null,
  "steps": [
    {
      "id": 1,
      "agent_name": "coordinator",
      "status": "completed",          ← "pending" | "running" | "completed" | "failed"
      "input_json": {},
      "output_json": { "doc_types": ["architecture"] },
      "started_at": "...",
      "completed_at": "..."
    }
    // ... up to 12 steps
  ]
}
```

### Get Job Logs (static, after completion)
```
GET /api/v1/jobs/{job_id}/logs
Auth: required
Response 200: [
  {
    "id": 1,
    "job_id": 42,
    "agent_name": "planner",
    "level": "info",              ← "info" | "warning" | "error"
    "message": "Documentation plan created — 4 sections",
    "extra_json": { "sections": 4 },
    "created_at": "2025-01-01T14:23:01Z"
  }
]
```

### Stream Job Logs (SSE — live, while running)
```
GET /api/v1/jobs/{job_id}/stream
Auth: pass token as query param: ?token=<access_token>
      OR use @microsoft/fetch-event-source with Authorization header

Response: text/event-stream

Stream events:
  data: {"id":1,"agent":"planner","level":"info","message":"...","extra":{}}
  data: {"id":2,"agent":"architecture","level":"info","message":"...","extra":{}}
  ...
  event: done
  data: {"status":"completed"}    ← or "failed", "cancelled"

  event: error
  data: {"detail":"Job not found"}

  event: timeout
  data: {}                        ← stream timed out (10 min max)
```

### Approve / Reject Job (Human Review)
```
POST /api/v1/jobs/{job_id}/approve
Auth: required (admin/manager/reviewer)
Body: {
  "approved": true,         ← true = approve, false = reject
  "comment": "Looks great!" ← optional
}
Response 200: { updated job object }

- approved=true  → job status becomes "running" (pipeline continues to publisher)
- approved=false → job status becomes "failed"
```

### Cancel Job
```
POST /api/v1/jobs/{job_id}/cancel
Auth: required (admin/manager)
Response 200: { updated job object with status: "cancelled" }
```

---

## Documents

### List Documents
```
GET /api/v1/documents?project_id={id}&doc_type={type}&limit=50&offset=0
Auth: required
Response 200: [
  {
    "id": 1,
    "title": "Architecture Overview",
    "doc_type": "architecture",
    "content_markdown": "# Architecture\n\n...",   ← may be truncated in list view
    "status": "published",                          ← "draft" | "published"
    "project_id": 5,
    "job_id": 42,
    "version": 1,
    "created_at": "...",
    "exports": [
      { "id": 1, "format": "docx", "storage_path": "exports/5/architecture.docx" }
    ]
  }
]
```

### Get Document
```
GET /api/v1/documents/{doc_id}
Auth: required
Response 200: { full document object including complete content_markdown }
```

### Publish Document
```
POST /api/v1/documents/{doc_id}/publish
Auth: required (admin/manager)
Response 200: { document object with status: "published" }
```

### Get Export Download URL
```
GET /api/v1/documents/{doc_id}/export?format=docx
Auth: required
Response 200: { "download_url": "https://minio-host/..." }
← presigned S3 URL, valid for ~15 minutes

Valid formats: "markdown" | "docx" | "mkdocs" | "docusaurus"
For "mkdocs" and "docusaurus" — these are site-wide exports (ZIP), not per-document.
The URL downloads a .zip file containing the entire MkDocs/Docusaurus site.
```

---

## Settings (Admin Only)

All settings endpoints require `role === "admin"`.

### Get LLM Configuration
```
GET /api/v1/settings/llm
Auth: required (admin)
Response 200: {
  "llm_base_url": "http://localhost:1234/v1",
  "api_key": "lm-studio",
  "default_model": "local-model",
  "quality_model": "local-model",
  "fast_model": "local-model",
  "max_tokens": 8192,
  "temperature": 0.2
}
```

### Update LLM Configuration
```
PUT /api/v1/settings/llm
Auth: required (admin)
Body: {
  "llm_base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "default_model": "gpt-4o-mini",
  "quality_model": "gpt-4o",
  "fast_model": "gpt-4o-mini",
  "max_tokens": 8192,
  "temperature": 0.2
}
Response 200: { "message": "LLM config updated" }
```

### Get All Templates
```
GET /api/v1/settings/templates
Auth: required (admin)
Response 200: {
  "templates": {
    "architecture": "You are a software architect...",
    "api": "You are an API documentation writer...",
    "modules": "...",
    "getting_started": "..."
  }
}
```

### Get Single Template
```
GET /api/v1/settings/templates/{doc_type}
Auth: required (admin)
Response 200: { "doc_type": "architecture", "template": "You are a software architect..." }
```

### Update Templates
```
PUT /api/v1/settings/templates
Auth: required (admin)
Body: { "templates": { "architecture": "new prompt...", "api": "new prompt..." } }
Response 200: { "message": "Templates updated" }
```

---

## Health Check

```
GET /health
Auth: none
Response 200: { "status": "ok" }
```

---

## Role Permissions Summary

| Endpoint | user | reviewer | manager | admin |
|---|---|---|---|---|
| Read projects/jobs/docs | ✓ | ✓ | ✓ | ✓ |
| Create project / add source | ✗ | ✗ | ✓ | ✓ |
| Create job | ✗ | ✗ | ✓ | ✓ |
| Cancel job | ✗ | ✗ | ✓ | ✓ |
| Approve/reject job | ✗ | ✓ | ✓ | ✓ |
| Publish document | ✗ | ✗ | ✓ | ✓ |
| Access settings | ✗ | ✗ | ✗ | ✓ |

---

## Error Response Format

All errors return:
```json
{
  "detail": "Human-readable error message"
}
```

Common HTTP status codes:
- `400` — validation error (bad input)
- `401` — not authenticated (missing/expired token)
- `403` — forbidden (insufficient role)
- `404` — resource not found
- `409` — conflict (e.g. duplicate email)
- `422` — Pydantic validation error (malformed request body)
- `500` — internal server error

---

## Pagination Pattern

All list endpoints support:
- `limit` (default 50, max 200)
- `offset` (default 0)

No cursor-based pagination — simple offset/limit.

---

## Notes for the Frontend Agent

1. **Token storage**: Use `localStorage` keys `docany_token` and `docany_refresh`
2. **Auto-refresh**: Create an Axios/fetch interceptor — if any request returns 401, call `POST /api/v1/auth/refresh`, update the stored token, retry the original request once
3. **SSE token**: Pass the token as `?token=<access_token>` query param on the stream URL since browsers' `EventSource` API doesn't support custom headers. Alternatively use `@microsoft/fetch-event-source` npm package
4. **CORS**: The backend allows all origins in dev — no proxy needed
5. **Date formatting**: All dates are ISO 8601 UTC strings. Display in local timezone using `Intl.DateTimeFormat` or `date-fns`
6. **Polling while running**: For job status updates when SSE is not in use (e.g. on the projects list), poll `GET /api/v1/jobs/{id}` every 5 seconds while `status === "running" || status === "pending"`. Stop polling on terminal status.
