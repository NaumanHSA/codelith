# Job Detail & Live Monitoring Page Prompt

**Reference**: `00-design-system-and-context.md`

Route: `/app/projects/[id]/jobs/[jobId]`

This is the most technically rich page. It shows the full lifecycle of a documentation generation job — from queued through each of the 12 agents to completion — with live streaming logs.

---

## Page Layout

**Two-column layout** (desktop): left `380px` sidebar panel + right main content area. Stack on mobile.

---

## Left Panel — Job Overview & Agent Pipeline

### Job Header Card

```
┌──────────────────────────────────────┐
│  Job #42                    ● running │
│  Project: My API Project              │
│  Started: 2 minutes ago               │
│                                       │
│  Doc types: [architecture] [api]      │
│  Formats:   [markdown] [docx]         │
│                                       │
│  [Cancel Job]          [View Docs]   │
└──────────────────────────────────────┘
```

- Status badge auto-refreshes (poll `GET /api/v1/jobs/{id}` every 5s while `status === "running"`)
- "Cancel Job" button: only shown if status is `running` or `pending`. Calls `POST /api/v1/jobs/{id}/cancel` with `ConfirmDialog` ("This will stop the AI pipeline. Generated docs up to this point may be partial.")
- "View Docs" button: only shown if status is `completed`. Links to `/app/documents?job_id={jobId}`

### Agent Pipeline (the 12-step pipeline tracker)

Below the job card, a vertical step list showing all 12 agents in pipeline order:

```
✓ coordinator          completed   0.4s
✓ planner              completed   2.1s
✓ repo_analyzer        completed   8.3s
✓ code_understanding   completed   45.2s
⟳ architecture         running     ...        ← animated spinner
○ strategy             pending
○ writer ×3            pending     (fan-out)
○ diagram              pending
○ validator            pending
○ reviewer             pending
○ formatter            pending
○ publisher            pending
```

**Each step row:**
- Icon: `✓` (green check), `⟳` (animated blue spinner), `○` (gray circle for pending), `✗` (red X for failed)
- Agent name (human-readable, convert `snake_case` to "Title Case")
- Status text: "completed", "running", "pending", "failed"
- Duration: shown only for completed steps
- For the `writer` step: show "(fan-out: writing N docs in parallel)"

**Data source**: `GET /api/v1/jobs/{id}` → `job.steps` array. Map `agent_name` to pipeline position.

Auto-refresh steps every 3 seconds while job is running.

**Agent name → display name map:**
```
coordinator        → "Coordinator"
planner            → "Planner"
repo_analyzer      → "Repo Analyzer"
code_understanding → "Code Understanding"
architecture       → "Architecture Mapper"
strategy           → "Documentation Strategy"
writer_agent       → "Writer (fan-out)"
diagram            → "Diagram Generator"
validator          → "Claim Validator"
reviewer           → "Quality Reviewer"
formatter          → "Output Formatter"
publisher          → "Publisher"
```

---

## Right Panel — Tabbed Content

Tabs: **Live Logs** · **Documentation Plan** · **Review** (only if `awaiting_review`) · **Results** (only if `completed`)

---

### Tab: Live Logs

This is the real-time streaming log view — the most important feature of this page.

**Log container**: dark terminal-style box (`bg-neutral-900 rounded-xl p-4 font-mono text-sm`), `max-height: 600px`, `overflow-y: auto`. Auto-scrolls to bottom as new lines arrive (with a "↓ Jump to bottom" button that appears when user has scrolled up).

**Each log line format:**
```
[14:23:01]  [architecture]  ℹ️  info   ReAct loop: reading app/config.py...
[14:23:02]  [architecture]  ⚠️  warn   File too large, skipping app/data/...
[14:23:04]  [writer_agent]  ✅  info   Section "API Reference" written (2.3k tokens)
[14:23:05]  [validator]     ❌  error  Claim failed: function not found
```

- Timestamp: `HH:MM:SS`
- Agent name: colored per agent (use a hash → color mapping, 12 distinct muted colors)
- Level icons: `ℹ️` info, `⚠️` warn, `❌` error
- Message text: white

**Log filter toolbar** (above the log box):
- Filter by agent dropdown (multi-select, "All agents" default)
- Filter by level: All · Info · Warn · Error
- Search input (filter messages containing text)
- "Download logs" button → download as `.txt` file
- "Auto-scroll" toggle (on by default)

**SSE Connection:**

Use the `EventSource` API to connect to:
```
GET /api/v1/jobs/{id}/stream
Headers: Authorization: Bearer <token>  (Note: EventSource doesn't support custom headers natively)
```

**Important**: The standard `EventSource` API does not support custom headers. Use one of these approaches:
1. Pass the token as a query param: `/api/v1/jobs/{id}/stream?token=<access_token>`  
   *(The backend should validate from query param as fallback)*
2. OR use the `@microsoft/fetch-event-source` npm package which supports custom headers

The stream emits:
```
data: {"id": 1, "agent": "planner", "level": "info", "message": "Plan created", "extra": {}}
data: {"id": 2, "agent": "architecture", "level": "info", "message": "Reading files...", "extra": {}}
...
event: done
data: {"status": "completed"}
```

When `event: done` is received:
- Stop the EventSource
- Show a toast: "Documentation complete!" (if `status === "completed"`) or "Job failed" (if `status === "failed"`)
- Refresh the job status card and agent pipeline

**Fallback for jobs that are already done (status is terminal):**
- If job is already `completed`/`failed`/`cancelled` when page loads, fetch all logs via `GET /api/v1/jobs/{id}/logs` and render them statically (no SSE needed).

---

### Tab: Documentation Plan

Shows the structured documentation plan the Planner agent created.

**Fetch**: look in `job.steps` for `planner` step → `output_json.plan` field.  
Or parse from agent logs: find a log message from `planner_agent` that contains JSON.

**Display as an expandable tree:**

```
📋 Documentation Plan — My API Project
├── 📄 Architecture Overview
│   ├── System Components
│   ├── Data Flow Diagrams
│   └── Technology Stack
├── 🔌 API Reference
│   ├── Authentication Endpoints
│   ├── Project Endpoints
│   └── Job Endpoints
├── 📦 Module Reference
│   ├── app/agents/
│   ├── app/workflows/
│   └── app/ingestion/
└── 🚀 Getting Started Guide
    ├── Prerequisites
    ├── Installation
    └── First Documentation Run
```

Each section is collapsible (expand/collapse chevron). Leaf nodes show a "status chip" if the writer agent has written it yet (`pending`, `writing`, `done`).

If the plan hasn't been generated yet (job still in early stages), show: "Plan will appear once the Planner agent completes."

---

### Tab: Review (only when `job.status === "awaiting_review"`)

Show a review panel:

**Header**: amber warning banner — "This job is awaiting your review before documents are published."

Below, a preview of each generated document section (read-only, rendered markdown):

For each doc in the job's generated docs:
- Card with doc type heading + a collapsed preview of the first 500 chars of content
- "Expand" to see full content

**Approve / Reject actions:**
```
┌─────────────────────────────────────────────────────┐
│  Review comment (optional textarea)                  │
│                                                      │
│  [Reject ✗]                    [Approve & Publish ✓]│
└─────────────────────────────────────────────────────┘
```

**API calls:**
```
POST /api/v1/jobs/{id}/approve
Body: { "approved": true, "comment": "Looks great!" }

POST /api/v1/jobs/{id}/approve
Body: { "approved": false, "comment": "Needs more detail in API section" }
```

On approve → show success toast → switch to "Results" tab  
On reject → show warning toast → job status changes to `failed`

Only users with role `reviewer`, `manager`, or `admin` can see this tab.

---

### Tab: Results (only when `job.status === "completed"`)

**Header**: green success banner — "✓ Documentation generated successfully"

**Stats row:**
- Documents created: N
- Total sections: N  
- Formats exported: markdown, docx (chips)
- Duration: Xs

**Documents list**: each generated doc as a card:
```
┌─────────────────────────────────────────┐
│ 🏗️  Architecture Overview               │
│     Markdown · 4,200 words              │
│                                         │
│  [Preview]  [Download MD]  [Download DOCX] │
└─────────────────────────────────────────┘
```

- "Preview" → opens document in the Document Viewer (described in `05-documents-and-exports.md`)
- "Download MD" → download the raw markdown content as a `.md` file
- "Download DOCX" → call `GET /api/v1/documents/{id}/export?format=docx` to get S3 presigned URL → open in new tab

If MkDocs or Docusaurus was requested, show a separate "Download MkDocs Site (ZIP)" / "Download Docusaurus Site (ZIP)" button at the bottom of the results section.
