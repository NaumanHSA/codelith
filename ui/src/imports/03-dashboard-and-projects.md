# Dashboard & Projects Pages Prompt

**Reference**: `00-design-system-and-context.md` — sidebar layout, status colors, shared components.

---

## App Shell (wraps all `/app/**` pages)

### Sidebar (fixed left, 240px wide)

**Top section:**
- Logo: small icon + "document-anything" wordmark
- Thin divider

**Navigation items** (icon + label, full-width clickable rows):
- 🏠 Dashboard → `/app`
- 📁 Projects → `/app/projects`
- 📄 Documents → `/app/documents`
- ⚙️ Settings → `/app/settings` *(only show if `user.role === "admin"`)*

**Active state**: `brand-500` left border + light blue background (`brand-500/10`) + bold label text

**Bottom section** (pinned to bottom):
- Avatar circle (first letter of user's name) + name + email (truncated)
- Logout button (icon only, tooltip "Log out") → clears tokens → redirects to `/`

**Collapse behavior:**
- At `< 1024px`: sidebar shows icons only (no labels), tooltip on hover
- At `< 768px`: sidebar hidden, replaced by hamburger button in top bar → slide-in drawer

### Top Bar (inside main content area)
- Current page breadcrumb (e.g., "Projects / My API Project / Job #42")
- Right: notification bell (placeholder, no functionality) + user avatar dropdown (Profile, Settings, Logout)

---

## Dashboard Page `/app`

The landing page after login — shows a high-level overview.

### Stats Row (4 cards)

| Card | Value source |
|---|---|
| Total Projects | Count from `GET /api/v1/projects` |
| Jobs This Month | Count `running + completed + failed` from recent jobs |
| Documents Generated | Count from `GET /api/v1/documents` |
| Avg Job Duration | Placeholder or computed from recent jobs |

Card style: white, `rounded-xl`, `border`, `p-6`. Large number (36px bold), label below in muted text. Small trend arrow (up/down) with percentage — hardcode a plausible placeholder if not available from API.

### Recent Jobs Table

Heading: "Recent Jobs" + "View all →" link to `/app/projects`

Table columns: **Project** · **Status** (StatusBadge) · **Doc Types** (DocTypeChips) · **Started** (relative time, e.g. "2 hours ago") · **Duration** · **Actions** (View button → job detail page)

Fetch: `GET /api/v1/projects` → for each project fetch `GET /api/v1/projects/{id}` and aggregate jobs. Show the 5 most recent across all projects.

Show `EmptyState` if no jobs yet.

### Quick Start Card

Only show when the user has 0 projects. Full-width card with:
- Illustration (simple SVG or placeholder box)
- Heading: "Generate your first documentation"
- Body: "Connect a GitHub repo or upload files. Our AI agents will do the rest."
- Button: "Create your first project →" → opens Create Project modal

---

## Projects List Page `/app/projects`

### Page Header
- Title: "Projects"
- Right: "+ New Project" button (primary) → opens Create Project modal

### Projects Grid

Responsive grid: 3 columns desktop, 2 tablet, 1 mobile.

**Each project card:**
```
┌─────────────────────────────────────┐
│ [Color icon]  My API Project        │
│               Created 3 days ago    │
│                                     │
│  3 sources    8 jobs    12 docs     │
│                                     │
│  ● running    [View →]  [⋮ menu]   │
└─────────────────────────────────────┘
```

- Color icon: a rounded square with first letter of project name, background color generated from name hash (deterministic, one of 8 brand colors)
- "● running" = latest job status badge (show nothing if no jobs)
- `[⋮ menu]`: dropdown → Edit name · Delete project (with `ConfirmDialog`)
- Clicking card (or "View →") → `/app/projects/[id]`

**Fetch**: `GET /api/v1/projects?limit=50`

---

## Create Project Modal

Triggered by "+ New Project" button. Full-screen overlay modal.

**Step 1 — Project Info:**
- Project name (required text input)
- Description (optional textarea, 2 rows)
- "Next →" button

**Step 2 — Add Source (optional, can skip):**
Four source type tabs: **GitHub** · **GitLab** · **Bitbucket** · **Local Path**

**GitHub tab:**
- URL input: `https://github.com/owner/repo` (validate URL format)
- Branch input (default: `main`)
- Token input (optional, for private repos) — type=password

**GitLab tab:** Same fields but label says GitLab URL

**Bitbucket tab:** Same

**Local Path tab:**
- Text input for absolute path on the server (e.g. `/home/user/myproject`)
- Note: "The server must have read access to this path"

**API calls:**
```
POST /api/v1/projects
Body: { "name": "...", "description": "..." }
→ returns { "id": 123, ... }

Then if source was filled:
POST /api/v1/projects/{id}/sources
Body: { "source_type": "github", "url_or_path": "https://github.com/...", "branch": "main", "config_json": {} }
```

On success → close modal → navigate to `/app/projects/{id}`

---

## Project Detail Page `/app/projects/[id]`

### Page Header
- Breadcrumb: Projects / **{project.name}**
- Right: "Edit" button (pencil icon) + "Delete" (trash icon, red, `ConfirmDialog`)
- PATCH `/api/v1/projects/{id}` for edit (name + description inline edit)
- DELETE `/api/v1/projects/{id}` for delete → redirect to `/app/projects`

### Tabs: Overview · Sources · Jobs · Documents

---

#### Tab: Overview
- Project name, description, created date, creator
- Stats: source count · job count · document count
- Latest job status widget (big status badge + "Go to job →" link)
- "+ Run Documentation Job" button (primary) → opens New Job modal (described in `04-job-workflow.md`)

---

#### Tab: Sources

**Table**: Source Type · URL/Path · Branch · Added

Each row: small icon for source type (GitHub icon, GitLab icon, folder icon) · truncated URL · branch name · relative date

"+ Add Source" button → opens Add Source modal (same as Step 2 from Create Project, but for existing project)

**API**: `GET /api/v1/projects/{id}` → `project.sources` array

---

#### Tab: Jobs

**Table** of all jobs for this project:

Columns: **#** (job id) · **Status** · **Doc Types** · **Started** · **Duration** · **Actions**

- Status: `StatusBadge`
- Doc types: row of `DocTypeChip` badges
- Duration: calculate from `started_at` to `completed_at` (or "In progress...")
- Actions: "View" → `/app/projects/[id]/jobs/[jobId]`; if `awaiting_review` → "Review" button; if `running` → "Cancel" button (with `ConfirmDialog`)

"+ New Job" button top-right of tab → New Job modal

**API**:
```
GET /api/v1/projects/{id}  →  job.steps are included
# Or fetch jobs list from the project's job list
```

---

#### Tab: Documents

Grid of generated documents (same as Documents page but scoped to this project). Covered in `05-documents-and-exports.md`.

---

## New Job Modal

A multi-step modal (3 steps):

### Step 1 — Pick Doc Types

Heading: "What should we document?"

Grid of toggleable doc type cards (multi-select):

| Doc Type | Icon | Description |
|---|---|---|
| `architecture` | 🏗️ | System architecture, module overview, dependency graph |
| `api` | 🔌 | API endpoints, request/response schemas |
| `modules` | 📦 | Module-by-module reference |
| `getting_started` | 🚀 | Quickstart guide, installation, first steps |
| `deployment` | ☁️ | Docker, K8s, CI/CD deployment guide |
| `contributing` | 🤝 | Contribution guide, dev setup |
| `changelog` | 📋 | Auto-generated changelog from git history |

Selected cards show a blue checkmark border. Must select at least 1.

### Step 2 — Output Formats

Multi-select toggle buttons (same pattern): **Markdown** · **DOCX** · **MkDocs** · **Docusaurus**

Markdown is pre-selected and not deselectable.

### Step 3 — Review Options

- Toggle: "Require human review before publishing" (checkbox)
- Informational note: "If enabled, the job will pause after AI review and wait for your approval before documents are saved."

"Generate Documentation →" button (full-width primary)

**API call:**
```
POST /api/v1/projects/{project_id}/jobs
Body: {
  "config": {
    "doc_types": ["architecture", "api"],
    "output_formats": ["markdown", "docx"],
    "requires_human_review": false
  }
}
Response: { "id": 42, "status": "pending", ... }
```

On success → close modal → redirect to `/app/projects/[id]/jobs/[jobId]`
