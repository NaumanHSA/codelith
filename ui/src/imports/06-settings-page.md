# Settings Page Prompt

**Reference**: `00-design-system-and-context.md`

Route: `/app/settings`  
**Access**: only show in sidebar and allow access if `user.role === "admin"`. Redirect to `/app` for other roles.

---

## Layout

Page header: "Settings" title  
Left sub-navigation list (tabs, vertical) + right content area.

Sub-nav items:
- LLM Configuration
- Documentation Templates
- Organization
- (User Profile — visible to all roles, placed at bottom of subnav)

---

## LLM Configuration Tab

Allows admins to configure the AI model settings used by all agents.

### Form fields:

| Field | Type | Default | Description |
|---|---|---|---|
| LLM Base URL | text input | `http://localhost:1234/v1` | OpenAI-compatible endpoint |
| API Key | password input | `lm-studio` | API key for the endpoint |
| Default Model | text input | `local-model` | Model ID for standard tasks |
| Quality Model | text input | `local-model` | Model ID for heavyweight tasks (architect, writer) |
| Fast Model | text input | `local-model` | Model ID for quick tasks |
| Max Tokens | number input | `8192` | Max tokens per LLM call |
| Temperature | range slider (0–1, step 0.05) | `0.2` | Controls creativity vs precision |
| Max ReAct Iterations | number input | `20` | Max tool-use loop iterations per agent |

Below the form:
- "Test Connection" button → makes a dummy call to the LLM endpoint and shows "✓ Connected" or "✗ Connection failed: {error}"
- "Save Changes" button (primary, full-width)

**API calls:**
```
GET /api/v1/settings/llm
Response: {
  "llm_base_url": "http://localhost:1234/v1",
  "api_key": "lm-studio",
  "default_model": "local-model",
  "quality_model": "local-model",
  "fast_model": "local-model",
  "max_tokens": 8192,
  "temperature": 0.2
}

PUT /api/v1/settings/llm
Body: { "llm_base_url": "...", "api_key": "...", ... }
```

Show a yellow info banner: "Changes take effect on the next documentation job. Running jobs use the configuration they started with."

---

## Documentation Templates Tab

Allows admins to customize the prompt templates used for each doc type.

### Layout

Left column: list of doc types (same as in New Job modal — architecture, api, modules, etc.)  
Clicking a doc type opens it in the right editor area.

### Editor area for each template:

- **Template name** (read-only label, e.g. "Architecture Template")
- **System prompt** (large textarea, monospace font, `min-height: 300px`) — the prompt injected into the architecture/writer agent
- **Variables reference** (collapsible section): shows available template variables like `{project_name}`, `{file_listing}`, `{api_context}` etc., each with a short description
- "Reset to Default" button (secondary, danger-tinted) — with `ConfirmDialog`
- "Save Template" button (primary)

**API calls:**
```
GET /api/v1/settings/templates
Response: { "templates": { "architecture": "...", "api": "...", ... } }

GET /api/v1/settings/templates/{doc_type}
Response: { "doc_type": "architecture", "template": "You are a software architect..." }

PUT /api/v1/settings/templates
Body: { "templates": { "architecture": "new prompt...", ... } }
```

---

## Organization Tab

Basic organization settings.

**Fields:**
- Organization name (text input)
- Organization slug (text input, lowercase, used in URLs — read-only if already set)
- Logo upload (file input, accepts PNG/JPG up to 2MB — upload placeholder UI, no actual backend endpoint)
- Default output formats (multi-select checkboxes: markdown, docx, mkdocs, docusaurus)

**API**: `GET /api/v1/organizations/{id}` and `PATCH /api/v1/organizations/{id}`

---

## User Profile Tab (all roles)

Available to all authenticated users (not just admin).

**Fields:**
- Full name (text input)
- Email (read-only — show as text with "(contact support to change)")
- Role (read-only badge — user cannot change their own role)
- Member since (read-only date)

**Change Password section:**
- Current password
- New password + confirm
- "Update Password" button

Clicking "Update Password" calls: `POST /api/v1/auth/change-password` (note: this endpoint may not exist yet — show UI but disable button with tooltip "Coming soon" if endpoint returns 404)

**Danger Zone** (red-bordered card at bottom):
- "Delete Account" button → `ConfirmDialog` ("This will permanently delete your account and all associated data. This cannot be undone.") → endpoint placeholder

---

## General UX Notes for Settings

- Show "Unsaved changes" banner if user navigates away with dirty form (use `beforeunload` event)
- All settings forms auto-load current values on mount
- Success toast on save: "Settings saved successfully"
- Error toast on failure: "Failed to save settings: {error message}"
