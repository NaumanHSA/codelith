# Documentation Sites — Plan

Turning the output from *a document per job* into **one living documentation site per
project**, grown a section at a time.

Decisions taken before writing this:

| Question | Answer |
|---|---|
| MkDocs/Material, or our own UI? | **Our own.** MkDocs and Docusaurus stay *export targets* only; the studio owns the reading experience and the theme |
| Who decides the structure? | **Analysis.** The site map is derived from the knowledge base, like doc-type suggestions are today |
| How do we build it? | **In stages**, each one shippable and useful on its own |

---

## The shape we are building

```
Project "neurosurfer"                     ← one site, grown over time
├── Home                                  ← generated last, knows the whole map
├── Quickstart            (getting_started)
├── API Reference         (api)
│   ├── overview.md
│   ├── endpoints.md                      ← each page is its own file
│   └── schemas.md
└── Architecture          (architecture)  ← added by a later job, slots in
```

Four levels, and the names are used consistently throughout this plan:

| Term | Is | Today's equivalent |
|---|---|---|
| **Site** | everything documented for one project | — |
| **Section** | a top-level nav entry | roughly a `doc_type` |
| **Page** | one `.md` file with a stable slug | a `##` section inside one blob |
| **Heading** | a heading inside a page → right-hand ToC | same |

Today a composition job produces **one flat `content_markdown` per doc type**, with
sections as `##` headings inside it. Everything below follows from splitting that.

## The idea the whole thing rests on

**Plan the entire site during analysis; build it in pieces.**

Because the map is decided up front, generating *API Reference* today writes pages into
a navigation that already knows *Architecture* will exist. Adding Architecture next
month slots in without renumbering, renaming or breaking a single link. And the nav can
show the pages that *could* exist, greyed out, each with a Generate button — the site
becomes a to-do list of its own documentation.

This is the existing `suggest_doc_types()` idea taken one level deeper: instead of
proposing a menu of document types with evidence and confidence, analysis proposes a
whole site map with the same grounding.

---

## Phase S1 — Foundations: schema and site map

*No UI, no generation changes. The map exists and is inspectable.*

- [ ] **`doc_sites`** — one row per project. Holds the ordered nav tree and site title.
- [ ] **`doc_pages`** — the core table: `site_id`, `section_slug`, `slug`, `title`,
      `doc_type`, `intent`, `status`, `order_index`, `content_markdown`, `job_id`,
      `kb_id`, `commit_sha`, `source_files_json`, `word_count`.
      Status is `planned | generating | ready | stale | orphaned | failed`.
- [ ] **`kb.site_map_json`** — the *proposal* from analysis, stored on the knowledge
      base beside `architecture_json`. Rebuilt on every analysis; never the source of
      truth for what exists.
- [ ] **New analysis agent `site_planner`** — runs after `narrative_writer`, on the
      quality tier. Input: module roles and summaries, entities, narratives, the
      architecture map. Output per page: `slug`, `title`, `doc_type`, one-sentence
      `intent`, `key_files`, `confidence`, `reason`.
      `key_files` validated against the whole KB, exactly like the composition planner.
- [ ] **Merge rules** (`SiteService.merge_proposal`) — the part that makes incremental
      growth safe:
      - proposed slug that does not exist → insert as `planned`
      - slug exists and is still proposed → keep it; title may update, **slug never**
      - slug exists and is no longer proposed → mark `orphaned`, never delete
- [ ] **Slug stability rules** — slugs are URLs and bookmarks. Assigned once from the
      first title, pinned forever, uniqueness enforced per section.
- [ ] `GET /projects/{id}/site` returns the map with per-page status.
- [ ] Tests: merge is idempotent; re-analysis of a changed repo never renames a slug;
      an orphaned page survives.

**Done when** analysing a project produces a full proposed site map, and re-analysing
it twice changes nothing.

---

## Phase S2 — Page-based generation

*Composition writes pages instead of one blob. Still shown in the existing reader.*

- [ ] **Composition takes a scope** — a list of page slugs or a whole section, instead
      of a list of doc types. `POST /projects/{id}/compose` gains `page_slugs`.
- [ ] **`kb_loader`** also loads the site map and the pages in scope.
- [ ] **`planner` moves down a level** — it no longer invents a document's structure;
      it plans the *headings within one page*, given that page's `intent` and
      `key_files`. Smaller, better-defined, and better grounded than today's job.
- [ ] **`writer` fans out per page**, and within a page per heading. The existing
      build-context-then-generate-concurrently machinery is unchanged — it simply
      operates one level deeper.
- [ ] **`publisher` writes `doc_pages` rows**, sets `ready`, records `job_id`,
      `commit_sha` and `source_files_json` for every page.
- [ ] **Cost gate** — `SITE_MAX_PAGES_PER_JOB`, and page count gated by evidence the
      same way narrative topics are. A 30-page site at one quality call per heading is
      an hour; this must be a deliberate choice, not an accident.
- [ ] Keep `documents` writing exactly as it does today, so nothing breaks while the
      new path is proven.

**Done when** composing `api` produces three real pages with correct provenance, and
the old single-document output still works.

---

## Phase S3 — The site UI

*Our own theme. This is the phase the user sees.*

- [ ] **Route** `/app/projects/:id/docs/:section?/:page?`
- [ ] **Four-pane layout**, all in the existing blueprint/terminal design language:
      - **top** — sticky bar: project, section tabs, "add a section"
      - **left** — pages in the active section; `planned` pages greyed with a Generate
        affordance
      - **centre** — the page, using the reading surface just rebuilt
      - **right** — heading ToC (exists today)
- [ ] **Prev / next** page navigation at the foot of each page.
- [ ] **Coverage view** — the whole map at a glance: what is built, what is planned,
      what is stale. The nav doubles as the product's roadmap for this project.
- [ ] **Search across pages** — client-side over titles and headings first; full text
      later.
- [ ] The old document reader keeps working for legacy documents.

**Done when** a user can read a generated site, move between pages, and start a
generation for a planned page from the nav.

---

## Phase S4 — Growing a site incrementally

*The workflow the whole design is for.*

- [ ] **Add a section to an existing site** — generate Architecture into the site that
      already has API Reference, no re-run of anything already written.
- [ ] **New agent `linker`** — deterministic, no LLM. Writers emit `[[page-slug]]`;
      the linker resolves them to real routes, validates every internal link and
      heading anchor, and reports anything unresolved. A docs site with broken links
      reads as broken, and a model cannot be trusted to invent relative paths.
- [ ] **Cross-page duplication control** — every page prompt carries the site map, not
      just its sibling headings. Three pages explaining the same middleware is what
      makes generated documentation feel cheap.
- [ ] **Nav-aware Home** — regenerated whenever the nav changes, because it is the one
      page whose content depends on the whole map.
- [ ] **Job scope reporting** — jobs keep the `analysis` / `composition` types and gain
      `scope_json`. The UI then says *"Job 12 · wrote API Reference (3 pages), updated
      Home"* instead of "job completed". `doc_pages.job_id` gives this almost for free.

**Done when** adding a second section leaves the first untouched, and every internal
link resolves.

---

## Phase S5 — Staleness and provenance

*The differentiator. Mostly bookkeeping we already collect.*

- [ ] **Per-page provenance, surfaced** — "written from these 12 files at commit
      `4065c2f`", with links. We already know the `key_files` and every retrieved
      chunk; we simply throw it away today. It is what makes generated docs auditable,
      which is what stops teams distrusting them.
- [ ] **Per-page staleness** — on a new commit, diff changed files against each page's
      `source_files_json` and mark only the affected pages `stale`. *"4 pages are out
      of date"*, with a one-click refresh of exactly those.
- [ ] **Regeneration as a diff** — when a page is rewritten, show what changed rather
      than a fresh blob. Combined with staleness this turns the product from a
      generator into a review workflow.
- [ ] **Per-page QA** — QA already fact-checks claims against retrieved evidence; at
      page granularity its score becomes actionable rather than decorative.

**Done when** pushing a commit that touches three files marks exactly the pages that
depend on them.

---

## Phase S6 — Export and versions

- [ ] **MkDocs / Docusaurus exports finally get what they always wanted** — a real page
      tree and a generated `nav:`. The formatters exist; they have never had pages to
      work with.
- [ ] **Static HTML export** of our own theme, so a site can be published anywhere.
- [ ] **Versions** — `doc_site_versions`, pages keyed by version, a version switcher in
      the UI. The schema should be shaped for this in S1 even though it is built last.

---

## Risks, stated plainly

- **This is the largest change since the analyse/compose split** — schema, planner,
  writer, publisher, API and UI. Phasing it so the current single-document path keeps
  working throughout is not optional.
- **Page planning becomes the highest-leverage call in the system.** It fixes the shape
  of everything downstream. Quality tier, and it needs `key_files`-style validation, or
  a bad map produces a bad site silently and permanently — slugs are forever.
- **Cost grows with page count.** The same evidence-gating that governs narratives has
  to govern pages, or a large repository becomes unusable.
- **Migration of existing documents.** Leave them as legacy single-page entries. Re-
  splitting a finished blob into pages is a lossy guess and not worth it.
- **Duplication across pages is harder than within a document** and will need iteration
  on prompts, not a one-shot fix.

## Open questions

1. Does a **section** always map 1:1 to a `doc_type`, or can one section hold pages
   from several types (a "Guides" section built from `getting_started` + `modules`)?
   Leaning: allow many-to-one, since the map is model-decided anyway.
2. Should a user be able to **reorder or rename** nav entries by hand, and should that
   survive re-analysis? Leaning: yes, with a `pinned` flag the merge respects.
3. How much should **Home** be generated versus templated from the map?

---

*Nothing in this document is implemented. Phase S1 is the next piece of work.*
