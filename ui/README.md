# Codelith studio

The web UI for Codelith: React 19, Vite 8, Tailwind 4, TypeScript. A pnpm project
that needs Node 20.19 or later.

```bash
pnpm install
pnpm dev        # http://localhost:5173, talking to the API at VITE_API_URL
pnpm build      # typecheck, the two render checks, then the bundle in dist/
```

`pnpm build` is what CI runs. The API serves `dist/` at its own root, so a build is
all a deployment needs. Nothing loads from a network at runtime: fonts, icons, logos
and three.js are all bundled.

## Where things are

```
src/
  index.css            base styles, the page frame, tables, atlas, animations
  styles/theme.css     every colour, as tokens; dark only
  assets/fonts/        Inter, Geist and JetBrains Mono, bundled
  app/
    App.tsx            routes, and the redirects from retired URLs
    lib/
      api.ts           all HTTP: JWT, one refresh on 401, retries
      types.ts         the API's shapes; ids are numbers
      icons.tsx        <Icon name>: every Lucide glyph the studio uses
      brands.tsx       <BrandMark name>: language, framework, host and provider logos
      kinds.ts         node, fact, symbol and topic kinds: label, colour, icon
      motion.ts        durations, easings, reduced motion, count-up and fill hooks
      narrate.ts       job stages: expected order, purpose, result, icon
    components/
      layout/          the shell: sidebar, tab strip (Tabs.tsx, tabState.ts), breadcrumbs, run dock
      primitives.tsx   icon tile, pill, list row, stat, codebase mark
      ui.tsx           buttons, inputs, panels, dialogs, the page header
      atlas/           the knowledge graph: 3D engine, layout worker, the parts model
                       (tiers, links, request paths), the 2D flow panel, inspector
      chat/            the assistant: messages, trace, citations/sources/thinking
      jobs/            the live run: stepper, writer fan-out, review gate
      docs/            the documentation site reader and writer
      settings/        model form, agents over MCP
    pages/app/         one file per route; routes.tsx lists them, rendered once per tab
```

## Pages

| Route | What it is |
|---|---|
| `/app` | Home: what Codelith does, the codebases, recent conversations and runs |
| `/app/projects` | Codebases, as a table |
| `/app/projects/:id` | A codebase: freshness, the four ways in, where an edit would hurt, stack, facts, narratives |
| `/app/projects/:id/graph` | The knowledge graph: the codebase's parts in columns, left to right in the order work moves through them; open one for its files, pick a file for who calls it, what it calls and its request path, in 3D and as a 2D flow beneath. `/atlas` and `/code` redirect here |
| `/app/chat` | Ask the code: conversation, with citations, sources and the answer's steps beside it |
| `/app/documentation` | Documentation: totals across codebases and one row per codebase; published sites and documents as tabs |
| `/app/projects/:id/docs/…` | The documentation site: read, write, revise, publish |
| `/app/projects/:id/drift` | Changes between two readings, and rewriting the pages they made stale |
| `/app/jobs`, `…/jobs/:id` | Runs: the history, and one run live |
| `/app/settings` | Models and their capabilities; agents attached over MCP |

## Rules worth knowing before changing anything

- **Pages live in tabs.** A codebase, a conversation and the lists each have a tab;
  "Ask about it" opens a new one and leaves the graph as it was. A hidden tab is kept
  inside `<Activity>`: its state stays, its effects stop until it is shown again.

- **Colours are tokens.** Use the Tailwind utilities `theme.css` exposes (`bg-panel`,
  `text-ink-mid`, `border-rule`…). The only hex values outside it are the kind and
  brand colours in `lib/kinds.ts` and `lib/brands.tsx`, which are data.
- **Icons are registered.** Add a Lucide name to `lib/icons.tsx` before using it; the
  build fails on one that is missing, and only registered icons are bundled.
- **Pages sit in `.page-frame`**: centred, 1440px at most, full height. A tool page
  fills the height with `h-full` and scrolls its own panes.
- **Motion respects reduced motion.** Script-driven motion goes through
  `lib/motion.ts`; CSS animations are stopped by the block at the end of `index.css`.
- **three.js stays in the atlas.** Only `components/atlas/` imports it, and the route
  is lazy.
- **Every number on screen comes from the API.** Nothing is invented for effect.
