# Documents Page & Document Viewer Prompt

**Reference**: `00-design-system-and-context.md`

---

## Documents List Page `/app/documents`

This page aggregates all generated documents across all projects.

### Page Header
- Title: "Documents"
- Filter bar (right-aligned):
  - Project dropdown filter (fetch from `GET /api/v1/projects`)
  - Doc type multi-select filter (architecture, api, modules, etc.)
  - Search input (searches document titles)
  - Sort: Newest first / Oldest first / Title A-Z

### Document Grid

Responsive card grid (3 cols desktop, 2 tablet, 1 mobile).

**Each document card:**
```
┌──────────────────────────────────────────┐
│  [🏗️ icon]                               │
│                                          │
│  Architecture Overview                   │
│  My API Project                          │
│                                          │
│  ● Published  ·  4,200 words  ·  3 days ago │
│                                          │
│  [markdown] [docx]                       │
│                                          │
│  [Open →]              [⋮]              │
└──────────────────────────────────────────┘
```

- Doc type icon: emoji or icon matching type (🏗️ architecture, 🔌 api, 📦 modules, 🚀 getting_started, ☁️ deployment, 🤝 contributing)
- Document title (bold)
- Project name (muted, smaller)
- Status badge (Published / Draft) + word count estimate + relative date
- Format chips showing available export formats
- "Open →" → `/app/documents/[id]`
- `⋮` dropdown: Preview · Download MD · Download DOCX · Delete (with `ConfirmDialog`)

**API**: `GET /api/v1/documents?project_id=&doc_type=&limit=50&offset=0`

Show `EmptyState` ("No documents yet — run your first documentation job") when list is empty.

---

## Document Viewer Page `/app/documents/[id]`

Full-featured document reading and export page.

### Layout: Two-panel

**Left panel (260px)**: Document outline / table of contents  
**Right panel (flex-1)**: Document content

---

### Left Panel — Outline

**Header**: document title (truncated) + doc type chip

**Table of contents**: auto-generated from H2/H3 headings in the markdown content.  
Rendered as a nested list. Clicking a heading scrolls the right panel to that section (anchor links).

Active heading (in viewport): highlighted in brand blue.

**Below TOC**: export actions:
```
Export as:
[ Download Markdown ]
[ Download DOCX     ]
[ Download MkDocs   ]   (only if available)
[ Docusaurus ZIP    ]   (only if available)
```

All download buttons → fetch presigned S3 URL from `GET /api/v1/documents/{id}/export?format=<fmt>` then trigger download.

Also show: "← Back to project" link and "Job #42" link (link to the source job).

---

### Right Panel — Document Content

**Toolbar** (sticky at top of right panel):
- Document title (editable inline — click to edit, `PATCH /api/v1/documents/{id}`)
- Right: "Edit" toggle (switches to edit mode) · "Version N" tag (placeholder) · "Publish" button (if not yet published)

**Reading mode** (default):
- Render `document.content_markdown` with `react-markdown`
- Enable: syntax highlighting for code blocks (rehype-highlight), GFM tables, task lists
- Mermaid diagram blocks: render as actual diagrams (use `mermaid.js`)
- Typography: `prose prose-neutral max-w-none` (Tailwind Typography plugin)
- Code blocks: dark background, line numbers, copy button top-right of each block
- Images: lazy-loaded, max-width 100%

**Edit mode** (when "Edit" toggle is on):
- Split view: left half = textarea / code editor (plain textarea or Monaco Editor), right half = live preview
- Auto-save with debounce (500ms) → `PATCH /api/v1/documents/{id}` with `{ "content_markdown": "..." }`
- Show "Saving..." / "Saved ✓" indicator

---

### Publish / Unpublish

If document is in `draft` status:
- Blue banner at top: "This document is not published yet." + "Publish Now" button
- `POST /api/v1/documents/{id}/publish` → marks as published

If already published:
- Green banner: "Published" + publication date

---

## API Calls for Documents

```
# List documents (with optional filters)
GET /api/v1/documents?project_id={id}&doc_type={type}&limit=50&offset=0

# Get single document
GET /api/v1/documents/{id}
Response: {
  "id": 1,
  "title": "Architecture Overview",
  "doc_type": "architecture",
  "content_markdown": "# Architecture\n\n...",
  "status": "published",
  "project_id": 5,
  "job_id": 42,
  "version": 1,
  "created_at": "2025-01-01T...",
  "exports": [
    { "id": 1, "format": "docx", "storage_path": "exports/5/architecture.docx" }
  ]
}

# Update document content
PATCH /api/v1/documents/{id}
Body: { "content_markdown": "..." }

# Publish document
POST /api/v1/documents/{id}/publish

# Get export download URL
GET /api/v1/documents/{id}/export?format=docx
Response: { "download_url": "https://..." }  ← presigned S3 URL

# Delete document
DELETE /api/v1/documents/{id}
```
