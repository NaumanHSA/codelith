# Plan: document-anything — Full-Stack Web App

## Context
Build a complete, modern SaaS web app for **document-anything**, an AI-powered documentation generation platform. The user provided 8 instruction files covering design system, all pages, auth, backend API, and UX patterns. The app must wire up to a real backend at `http://localhost:8000`.

## Tech Stack
- **React Router v7** for routing (already installed)
- **Sonner** for toasts (already installed)
- **Lucide React** for icons (already installed)
- **Tailwind CSS v4** for styling
- **react-markdown + remark-gfm + rehype-highlight** → install via pnpm (needed for document viewer)
- **Native EventSource** for SSE job log streaming

## Color Theme — Portfolio-inspired, light/dark toggle
Inspired by the user's portfolio: warm off-white base, monospace headings, extremely minimal color. A single accent (blue) used only for primary CTAs and active states.

**Light mode (default):**
- Background: `#f9f7f4` (warm off-white/cream), surface/card: `#ffffff`, border: `#e5e2dc`
- Text primary: `#1a1917`, text secondary: `#6b6760`
- Accent (CTAs, active nav highlight, links): `#1a56db`
- Sidebar: white with `#f3f1ee` active bg, black left-border on active item
- Status: pending=gray, running=blue, awaiting_review=amber, completed=green, failed=red

**Dark mode (togglable):**
- Background: `#111110`, surface: `#1c1b1a`, border: `#2e2d2b`
- Text primary: `#e8e6e3`, text secondary: `#8a8784`
- Accent: `#4f8ef7`
- Sidebar: `#161514` with `#252422` active bg

**Typography:**
- Headings (hero, section): `JetBrains Mono` or `monospace` stack — echoes portfolio aesthetic
- Body: `Inter`, clean sans-serif
- Code blocks: `JetBrains Mono`

**Landing page:** Pure white background (`#ffffff`), black/gray text. No colored section backgrounds except a single light-gray strip for social proof. Accent blue only on CTAs.

**Theme toggle:** Sun/moon button in app top bar; preference saved to `localStorage`; toggles `dark` class on `<html>`.

## File Structure

### Core Infrastructure
- **`src/app/lib/api.ts`** — Fetch wrapper with Bearer auth, 401 → refresh interceptor, base URL `http://localhost:8000`
- **`src/app/lib/auth.tsx`** — `AuthContext` + `useAuth()`: reads `docany_token`/`docany_refresh` from localStorage, exposes `user`, `isAuthenticated`, `login()`, `logout()`, `refreshToken()`
- **`src/app/lib/types.ts`** — TypeScript types for all API shapes (User, Project, Job, Document, Step, Log, etc.)

### Shared Components (`src/app/components/shared/`)
- **`StatusBadge.tsx`** — colored badge for job/doc status
- **`Spinner.tsx`** — animated loading spinner
- **`EmptyState.tsx`** — empty state with icon + message + optional CTA
- **`ConfirmDialog.tsx`** — modal with confirm/cancel using Radix Dialog
- **`CopyButton.tsx`** — copy-to-clipboard with check feedback
- **`PageHeader.tsx`** — page title + breadcrumb + action slot

### Layout Components (`src/app/components/layout/`)
- **`AppShell.tsx`** — sidebar (240px) + top bar + main content; collapses to icons at <1024px, hamburger drawer at <768px
- **`Sidebar.tsx`** — nav items, active state, admin-only settings link, profile + logout at bottom
- **`ProtectedRoute.tsx`** — checks auth, redirects to `/auth/login` if not authenticated

### Pages
1. **`src/app/pages/LandingPage.tsx`** — 10-section marketing page (navbar, hero with terminal mockup, social proof, features grid, how it works, output formats tabs, live monitoring section, pricing, CTA banner, footer)
2. **`src/app/pages/auth/LoginPage.tsx`** — centered card, email+password, API call, store tokens, redirect `/app`
3. **`src/app/pages/auth/RegisterPage.tsx`** — full name+email+password+confirm, strength bar, terms, API call
4. **`src/app/pages/app/DashboardPage.tsx`** — 4 stats cards + recent jobs table + quick start card
5. **`src/app/pages/app/ProjectsPage.tsx`** — project grid + create project modal (2-step: name → source)
6. **`src/app/pages/app/ProjectDetailPage.tsx`** — 4 tabs: Overview / Sources / Jobs / Documents + new job modal (3-step)
7. **`src/app/pages/app/JobDetailPage.tsx`** — 2-column: left panel (job header + 12-step pipeline tracker) + right panel tabs (Live Logs SSE / Plan / Review / Results)
8. **`src/app/pages/app/DocumentsPage.tsx`** — document grid with filters
9. **`src/app/pages/app/DocumentViewerPage.tsx`** — 2-panel: outline + markdown content + edit mode
10. **`src/app/pages/app/SettingsPage.tsx`** — 4 vertical tabs: LLM Config / Templates / Organization / User Profile

### Entry Point
- **`src/app/App.tsx`** — React Router v7 `BrowserRouter` with all routes nested under auth context

## Routing Structure
```
/                           → LandingPage
/auth/login                 → LoginPage
/auth/register              → RegisterPage
/app                        → AppShell (ProtectedRoute)
  /app                      → DashboardPage
  /app/projects             → ProjectsPage
  /app/projects/:id         → ProjectDetailPage
  /app/projects/:id/jobs/:jobId → JobDetailPage
  /app/documents            → DocumentsPage
  /app/documents/:id        → DocumentViewerPage
  /app/settings             → SettingsPage (admin check)
```

## Key Implementation Details

### API Client (`api.ts`)
- Base `apiFetch(path, options)` with auto-attach Bearer token
- 401 handling: call `POST /api/v1/auth/refresh`, retry once, logout on second 401
- Helper methods: `get()`, `post()`, `patch()`, `del()`

### SSE Job Logs
- Use native `EventSource` with token as query param: `GET /api/v1/jobs/{id}/stream?token=<token>`
- Parse JSON from `event.data`, append to log array
- On `event: done` → close EventSource, refresh job status
- Fallback to `GET /api/v1/jobs/{id}/logs` if job is already finished

### Live Polling
- Job status: auto-refresh every 5s while `status === "running" | "pending"`
- Agent pipeline steps: refresh every 3s while running

### Document Markdown Rendering
Install: `react-markdown`, `remark-gfm`, `rehype-highlight`
- Use `<ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>` 
- Wrap in `prose prose-neutral max-w-none` for typography

## Packages to Install
```
pnpm add react-markdown remark-gfm rehype-highlight
```

## Verification
1. Landing page renders all 10 sections with navigation
2. Register creates account, stores tokens, redirects to `/app`
3. Login with existing credentials works
4. Dashboard shows stats (or empty state)
5. Create project modal → project card appears in grid
6. Start job → navigate to job detail → logs stream in terminal
7. Completed job → results tab shows documents
8. Document viewer renders markdown with outline
9. Settings page (admin) loads and saves LLM config
10. Logout clears localStorage and redirects to `/`
