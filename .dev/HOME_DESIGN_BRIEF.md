# Design brief — the Home page

Prompt for a UI/UX specialist. Paste whole; the data inventory is the part that keeps
proposals buildable.

---

## What the product is

**Codelith** reads a codebase once and turns it into a knowledge base. Everything else is
an app that consumes that knowledge base: **Documentation** (writes structured docs),
**Ask the code** (grounded Q&A with checked citations), **Quality** (linter findings joined
to blast radius). More apps are coming. The analysis is the base; the apps unlock after it.

It runs entirely on your own machine. That is the product's claim, and it constrains the
design — see Constraints.

## What I want designed

The **Home** page (currently called "Dashboard" — rename is part of this). Screenshots of
today's Home and today's project detail page are attached.

### The problems

1. **Home doesn't have a thesis.** It's a launcher, a status board and a stats page at
   once, and does none of them well. Pick what it is for and commit.
2. **The hero numbers read `1 / 0 / 1 / 0`.** Projects, pages written, jobs run, active
   jobs. A row of zeroes teaches people to ignore the row. Either these become something
   that means something at low counts, or they go.
3. **The app cards repeat.** The same three cards appear on Home and again on the project
   page. On Home the unanswered question is *which codebase*; on the project page the
   codebase is already chosen and the card should be saying *what state this app is in
   here* — 23 pages planned and none written, no conversations yet, never checked. Same
   component, two different jobs, currently doing neither.
4. **The analysis is under-shown.** The knowledge base is the whole product and it's a
   sidebar widget. There is a lot more in it than is on screen (inventory below).
5. **It isn't eye-catching.** Everything is a flat bordered rectangle at the same visual
   weight, so nothing leads.

### Directions I'm already leaning toward — challenge them if they're wrong

- **App cards want a visual.** Not decoration: something that carries information. See the
  constraint on imagery below before proposing photography.
- **Bring the project detail onto Home**, with a project selector. One analysed codebase is
  the common case and making people click through to see anything is a wasted screen.
  Design for 0, 1, and 20+ projects — the selector that's elegant at 3 is a problem at 30.
- **Home should answer "what changed since I last looked."** Nothing on the page does.

Add whatever else you think belongs. I'd rather see an argument than a compliant mockup.

---

## The data that actually exists

Design from this. Anything invented has to be built in the backend first, so if a proposal
needs something not on this list, say so explicitly and it becomes a scoped decision.

**Per project**
`name` · `description` · `status` · `created_at` / `updated_at` · `kb_status`
(ready / stale / degraded / pending / running / failed) · `apps_ready` (bool) ·
`stats {source_count, job_count, doc_count, page_count}` · `latest_job {id, status}`

**Source**
Provider + URL · branch · commit SHA · `file_count` 387 · `analysable_files` 257 ·
language breakdown `{python: 257}`

**Knowledge base** — the rich one, from a real 257-file repo
- `modules` 45 · `entities` 143 · `indexed_chunks` 1692 · `site_pages` 23
- `summarised_modules` 40 · **`missing_summaries` 4** — the analysis knows its own gaps
- **Code graph**: `symbols` 3244 · `calls` 2525 · `imports` 745 · `packages` 147 · `files` 257
- **Role distribution**: service 28, api 4, utility 4, cli 3, config 2, data_access 2,
  schema 1, test 1
- **Entity kinds**: env_var 67, dependency 43, service 9, external_api 6, route 4,
  infra_resource 4, entrypoint 3, cli_command 2, config_file 2, datastore 2, test_suite 1
- **Narrative topics** (12): architecture, cli_usage, configuration, data_model, deployment,
  error_handling, integrations, observability, overview, request_lifecycle,
  state_management, testing
- **`suggested_doc_types`** — each with a confidence and a *reason in plain language*:
  architecture 0.9 "45 modules mapped across the codebase" · deployment 0.9
  "4 infrastructure definitions found" · api 0.7 "4 HTTP routes detected" ·
  getting_started 0.7 "3 entrypoints and 43 declared dependencies" · modules 0.6
- Entrypoints, key dependencies, and a sample of the HTTP surface (route → handler)

**Jobs** — type, status, timestamps, duration, per-step progress, 14-day activity histogram

**Quality** (only after an explicit run — nothing runs on page load) — error/warning counts,
untested surface, dependency issues, layering violations

### Things this data makes possible that nobody has asked for yet

Judge these; they're candidates, not requirements.

- **Analysis drift.** The KB pins a commit SHA. The branch has moved on. "Your analysis is
  N commits behind `main`" is a real, computable prompt to re-run.
- **`suggested_doc_types` is the best content on the page and isn't on the page.** The
  product has an opinion about what you should write next, and a stated reason for it.
- **`missing_summaries: 4`** — honest coverage of the analysis itself.
- **23 site pages planned, 0 written.** That is not the stat "0 documents", it's a piece of
  work sitting there half-done.
- **Resume**: last conversation, last job, the draft site.

---

## Constraints — these are hard

- **No external network at runtime.** No CDN, no remote images, no web fonts, no stock
  photography. Fonts are bundled. *This directly limits the "card image" idea:* imagery
  must be inline SVG, CSS, or generated from the project's own data. I'd argue that's the
  better answer anyway — a blueprint/terminal product with stock developer photography
  would look like every other dev tool. Consider per-app generated marks, or letting each
  card's visual be a small live rendering of that project's real numbers.
- **Light theme, design tokens only.** `--paper` `--ink` `--hot` (orange) `--rule` `--sunk`
  `--panel`, exposed as Tailwind utilities. Never a raw Tailwind colour. A dark variant
  isn't built but the tokens are structured for it — don't design something that can only
  work in light.
- **Character**: blueprint / technical drawing / terminal. Monospace, hairline rules,
  numbered nav (`01 Dashboard`, `02 Codebases`…), small rotated-square markers, `tag`
  micro-labels. Precision instrument, not consumer SaaS. Keep this — sharpen it.
- **Stack**: React 19 + Tailwind 4. No component library, no animation library, no
  charting library. Any chart is hand-built SVG.
- **Left rail is fixed at 188px** and stays. Design within the remaining width, ~1180px
  content max, and it must hold up on a very wide monitor (see screenshot — the current
  page floats in a sea of empty paper).

## What to deliver

1. **A thesis for Home in one sentence** — what it's for, and what it therefore *isn't*.
2. **Layout** at three states: no projects, one analysed project, many projects.
3. **The app card**, resolved for both contexts (Home vs project page), with whatever
   visual treatment you're proposing, and an argument for why it earns its space.
4. **How the analysis gets shown richly** — this is the piece I most want ideas on.
5. **Anything you'd cut.** Especially welcome.

Where you disagree with my framing above, say so and show the alternative.
