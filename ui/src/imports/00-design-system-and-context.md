# document-anything — UI Master Context & Design System

Feed this file first before any page-specific prompt. Every page prompt references the design system defined here.

---

## What Is This Application?

**document-anything** is an AI-powered documentation generation platform. It takes a code repository (GitHub/GitLab/Bitbucket/local) or uploaded files, runs a multi-agent AI pipeline (12 specialized agents), and produces structured technical documentation in Markdown, DOCX, MkDocs, or Docusaurus format.

The product has two distinct surfaces:
1. **Landing page** — public marketing/product page for visitors
2. **App (playground)** — authenticated workspace where users manage projects, run documentation jobs, and view/export results

---

## Recommended Tech Stack

- **Framework**: Next.js 14+ (App Router) — or React + Vite if simpler
- **Styling**: TailwindCSS + shadcn/ui component library
- **State / data**: TanStack Query (React Query) v5 for server state; Zustand for local UI state
- **Auth**: JWT stored in `httpOnly` cookies or `localStorage` (the backend returns a Bearer token)
- **Streaming**: native `EventSource` API for the SSE job-log stream
- **Markdown rendering**: `react-markdown` + `rehype-highlight` for code blocks
- **Icons**: Lucide React
- **Charts**: Recharts (for job duration / success rate stats on dashboard)
- **Notifications**: Sonner (toast library)

---

## Design System

### Color Palette

| Token | Hex | Usage |
|---|---|---|
| `brand-900` | `#0f172a` | Dark navy — primary background in dark mode, headings |
| `brand-700` | `#1e3a5f` | Deep blue — sidebar, nav |
| `brand-500` | `#2563eb` | Electric blue — primary CTA buttons, active states, links |
| `brand-300` | `#93c5fd` | Light blue — hover glows, subtle accents |
| `accent-500` | `#7c3aed` | Purple — AI/agent tags, plan badges |
| `accent-300` | `#c4b5fd` | Soft purple — agent status pills |
| `success` | `#16a34a` | Green — completed status |
| `warning` | `#d97706` | Amber — awaiting_review status, warnings |
| `danger` | `#dc2626` | Red — failed status, errors |
| `neutral-50` | `#f8fafc` | Off-white — page backgrounds |
| `neutral-100` | `#f1f5f9` | Card backgrounds |
| `neutral-900` | `#0f172a` | Body text |

### Typography

- **Font**: Inter (Google Fonts) — sans-serif throughout
- **Hero heading**: 56px / 700 weight / tight leading
- **Section heading**: 36px / 700
- **Card title**: 18px / 600
- **Body**: 16px / 400, line-height 1.6
- **Code / monospace**: JetBrains Mono or Fira Code, 14px

### Component Style Rules

- **Cards**: `rounded-xl`, `shadow-sm`, `border border-neutral-200`, white background
- **Buttons primary**: `bg-brand-500 text-white hover:bg-blue-700 rounded-lg px-5 py-2.5 font-semibold`
- **Buttons secondary**: `border border-neutral-300 bg-white hover:bg-neutral-50 rounded-lg`
- **Buttons destructive**: `bg-danger text-white hover:bg-red-700`
- **Inputs**: `rounded-lg border border-neutral-300 focus:ring-2 focus:ring-brand-500 px-3 py-2`
- **Badges/pills**: `rounded-full text-xs font-semibold px-2.5 py-0.5`
- **Sidebar**: dark (`bg-brand-900` or `bg-brand-700`), white text, icon + label nav items
- **Dividers**: `border-neutral-200`
- **Shadows**: prefer `shadow-sm` normally, `shadow-lg` for modals/popovers
- **Transitions**: `transition-all duration-200` on interactive elements

### Status Color Map

| Job / step status | Badge style |
|---|---|
| `pending` | Gray pill |
| `running` | Blue pill + spinning indicator |
| `awaiting_review` | Amber pill |
| `completed` | Green pill |
| `failed` | Red pill |
| `cancelled` | Gray strikethrough text |

### Layout Grid

- **Landing**: full-width sections, max-width `1280px` centered container
- **App shell**: fixed sidebar `240px` wide + main content area (`flex-1`, `min-h-screen`)
- **Main content**: padding `px-6 py-8`, max-width `1100px`
- **Responsive**: sidebar collapses to icon-only at `< 1024px`, hamburger drawer at `< 768px`

---

## Backend Base URL

All API calls go to: `http://localhost:8000` (dev) or the value of `NEXT_PUBLIC_API_URL` environment variable.

All authenticated requests include:
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

The full API reference is in `07-api-reference.md`.

---

## Navigation Structure (App)

```
Sidebar
├── Dashboard          /app
├── Projects           /app/projects
│   └── [id]          /app/projects/[id]
│       └── Jobs       /app/projects/[id]/jobs
│           └── [jobId] /app/projects/[id]/jobs/[jobId]
├── Documents          /app/documents
├── Settings           /app/settings         (admin/manager only)
└── ── bottom ──
    Profile / Logout
```

---

## Shared Components to Build

These are reused across pages — build them once:

| Component | Description |
|---|---|
| `StatusBadge` | Renders colored pill from a status string |
| `AgentLogLine` | Single log entry: icon (level) + agent name + message + timestamp |
| `DocTypeChip` | Small badge for doc types: architecture, api, modules, etc. |
| `FormatChip` | Chip for output formats: markdown, docx, mkdocs, docusaurus |
| `EmptyState` | Centered illustration + heading + CTA for empty lists |
| `ConfirmDialog` | Modal for destructive actions (delete project, cancel job) |
| `CopyButton` | Copy-to-clipboard icon button |
| `Spinner` | Animated loading spinner |
| `PageHeader` | Page title + optional breadcrumb + right-side action buttons |
