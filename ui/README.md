# document-anything — UI

React studio for the [document-anything](../README.md) API. Lives in the same repo as the
backend; there is no separate UI repository.

## Running

```bash
cd ui
npm install
npm run dev          # http://localhost:5173
```

The API must be running separately (`./dev.sh` from the repo root).

## Configuration

The API base URL comes from `VITE_API_URL`, defaulting to `http://localhost:8000`.
Override it in `ui/.env.local` (gitignored):

```env
VITE_API_URL=http://localhost:8001
```

## Conventions

- **Dark theme only.** There is no light mode and no toggle — `index.html` sets
  `class="dark"` on `<html>` and `src/app/lib/theme.tsx` keeps it there. Style with the
  CSS custom properties in `src/styles/theme.css` (`bg-background`, `text-muted-foreground`,
  `text-brand`, …) rather than hardcoded Tailwind colors, so everything stays consistent.
- Headings use `var(--font-mono)` (JetBrains Mono); body copy uses `var(--font-sans)` (Inter).
- All HTTP goes through `src/app/lib/api.ts`, which attaches the JWT and transparently
  refreshes it on a 401.

## Layout

```
src/
  app/
    App.tsx           Router
    lib/              API client, auth context, theme, shared types
    components/       layout (AppShell, Sidebar), shared widgets, shadcn/ui primitives
    pages/
      LandingPage.tsx Public single-page landing + inline sign-in / register
      auth/           Standalone login + register routes
      app/            Dashboard, projects, jobs, documents, settings
  styles/             Tailwind entry + theme tokens
  imports/            Design-system notes carried over from the original Figma export
```
