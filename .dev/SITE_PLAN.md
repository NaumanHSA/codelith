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

## Phase S1 — Foundations: schema and site map ✅

*No UI, no generation changes. The map exists and is inspectable.*

- [x] **`doc_sites`** — one row per project. Holds the ordered nav tree and site title.
- [x] **`doc_pages`** — the core table: `site_id`, `section_slug`, `slug`, `title`,
      `doc_type`, `intent`, `status`, `order_index`, `content_markdown`, `job_id`,
      `kb_id`, `commit_sha`, `source_files_json`, `word_count`.
      Status is `planned | generating | ready | stale | orphaned | failed`.
      Also carries `key_files_json`, `confidence` and `reason` — the planner's
      evidence, which is what makes a *proposed* page auditable before it is written.
- [x] **`kb.site_map_json`** — the *proposal* from analysis, stored on the knowledge
      base beside `architecture_json`. Rebuilt on every analysis; never the source of
      truth for what exists.
- [x] **New analysis agent `site_planner`** — runs after `narrative_writer`, on the
      quality tier. Input: module roles and summaries, entities, narratives, the
      architecture map. Output per page: `slug`, `title`, `doc_type`, one-sentence
      `intent`, `key_files`, `confidence`, `reason`.
      `key_files` validated against the whole KB, exactly like the composition planner.
      Falls back to a map derived from `suggest_doc_types()` when the call fails, and
      marks the KB `DEGRADED` when it does.
- [x] **Merge rules** (`SiteService.merge_proposal`) — the part that makes incremental
      growth safe:
      - proposed slug that does not exist → insert as `planned`
      - slug exists and is still proposed → keep it; title may update, **slug never**
      - slug exists and is no longer proposed → mark `orphaned`, never delete
      - an empty proposal is a no-op, so a failed call cannot retire a written site
- [x] **Slug stability rules** — slugs are URLs and bookmarks. Assigned once from the
      first title, pinned forever, uniqueness enforced per section.
- [x] `GET /projects/{id}/site` returns the map with per-page status.
- [x] Tests: merge is idempotent; re-analysis of a changed repo never renames a slug;
      an orphaned page survives.

**Done when** analysing a project produces a full proposed site map, and re-analysing
it twice changes nothing. ✅

Answered along the way: open question 2 — a `pinned` flag on pages and nav entries,
which the merge respects in both directions (a pinned page keeps its title and order,
and survives falling out of a proposal). Open question 1 stands as "many-to-one":
`section_slug` and `doc_type` are separate columns, so one section may hold pages of
several types.

---

## Phase S2 — Page-based generation ✅

*Composition writes pages instead of one blob. Still shown in the existing reader.*

- [x] **Composition takes a scope** — a list of page slugs or a whole section, instead
      of a list of doc types. `POST /projects/{id}/compose` gains `page_slugs`, which
      accepts both `"api/endpoints"` and `"api"`. Resolved in `SiteService.resolve_scope`
      *before* the job is created, so a bad scope is a 422 rather than a job that dies
      ten minutes into a worker.
- [x] **`kb_loader`** also loads the site map and the pages in scope, and claims them
      `generating` so the nav shows them working.
- [x] **`planner` moves down a level** — it no longer invents a document's structure;
      it plans the *headings within one page*, given that page's `intent` and
      `key_files`. Smaller, better-defined, and better grounded than today's job.
- [x] **`writer` fans out per page**, and within a page per heading. The existing
      build-context-then-generate-concurrently machinery is unchanged — it simply
      operates one level deeper.
- [x] **`publisher` writes `doc_pages` rows**, sets `ready`, records `job_id`,
      `commit_sha` and `source_files_json` for every page. Pages a job claimed but
      never wrote are swept to `failed` rather than stranded in `generating`.
- [x] **Cost gate** — `SITE_MAX_PAGES_PER_JOB` (8), plus an evidence gate: asking for a
      whole *section* writes only the pages that are unwritten and anchored on real
      files. Naming a page outright always honours it — that is how you regenerate one.
- [x] Keep `documents` writing exactly as it does today, so nothing breaks while the
      new path is proven.

**Done when** composing `api` produces three real pages with correct provenance, and
the old single-document output still works. ✅

Two things had to be fixed on the way, both of which would have silently degraded the
new path:

* **QA, diagrams and exports all keyed off `doc_type`.** Three pages of type `api` are
  three documents: QA fact-checked one and passed the other two, every page got the
  same diagram, and two DOCX exports overwrote each other. All three now key on
  `doc_key()` — the page address, falling back to the doc type.
* **`SECTION_WRITE` never rendered `$already_written`.** The placeholder abutted the
  next word, so `string.Template` read one identifier `already_writtenContext`, found
  no such key, and left it verbatim — the "do not repeat the other sections"
  instruction has never reached a writer. `PromptTemplate.render` now raises on an
  unsupplied identifier, and a unit test scans every template for the same shape.

---

## Phase S3 — The site UI ✅

*Our own theme. This is the phase the user sees.*

- [x] **Route** `/app/projects/:id/docs/:section?/:page?` — no section shows the
      coverage view rather than a 404.
- [x] **Four-pane layout**, all in the existing blueprint/terminal design language:
      - **top** — sticky bar: project, section tabs, search, a coverage meter
      - **left** — pages in the active section; `planned` pages greyed with a Generate
        affordance
      - **centre** — the page, using the reading surface just rebuilt
      - **right** — heading ToC
- [x] **Prev / next** page navigation at the foot of each page, crossing section
      boundaries the way a book does.
- [x] **Coverage view** — the whole map at a glance: what is built, what is planned,
      what is stale, plus a "write the N remaining" action per section. Retired
      (orphaned) pages get their own list, still readable.
- [x] **Search across pages** — client-side over titles, sections and intents, so a
      *planned* page is findable before it exists. Full text later.
- [x] The old document reader keeps working for legacy documents.

**Done when** a user can read a generated site, move between pages, and start a
generation for a planned page from the nav. ✅ *Verified against the real API with a
seeded site for the neurosurfer project.*

Two things were extracted rather than duplicated, because the site and the legacy
reader must be indistinguishable: `components/docs/DocMarkdown.tsx` (the reading
surface, still lazily loaded — it is a 323 kB chunk) and `components/docs/Toc.tsx`
(the heading rail and its scroll-spy). `lib/site.ts` holds everything derived from
the map — reading order, prev/next, coverage, search — because all four have to agree
that **planned pages are part of the site**.

An unplanned addition: `GET /projects/{id}/site/pages/{section}/{slug}`. The map is
fetched on every nav render and a thirty-page site's markdown is megabytes, so page
content had to be a separate call.

---

## Phase S4 — Growing a site incrementally ✅

*The workflow the whole design is for.*

- [x] **Add a section to an existing site** — generate Architecture into the site that
      already has API Reference, no re-run of anything already written. Falls out of
      S2's evidence gate: a whole-section request writes only the unwritten pages.
- [x] **New agent `linker`** — deterministic, no LLM. Writers emit `[[page-slug]]`;
      the linker resolves them to real routes, validates every internal link and
      heading anchor, and reports anything unresolved. A docs site with broken links
      reads as broken, and a model cannot be trusted to invent relative paths.
      It sits between `writer` and `diagram`, which is also the join point for the
      writer fan-out — the first node that sees every page of the job at once.
- [x] **Cross-page duplication control** — every page prompt carries the site map, not
      just its sibling headings. The neighbour list doubles as the vocabulary of
      link targets, so the same text prevents duplication *and* enables linking.
- [x] **Nav-aware Home** — derived from the map on every read rather than stored, so
      it cannot fall behind the nav. Prose is the overview narrative analysis already
      wrote; the index is the map itself, rendered by the reader.
- [x] **Job scope reporting** — `jobs.scope_json`, written at creation from the
      resolved scope. The UI now says *"API Reference · 3 pages"* on a job row and in
      the run header. Recorded at creation rather than derived from `doc_pages.job_id`
      so it exists while the job is still queued, and survives one that failed.

**Done when** adding a second section leaves the first untouched, and every internal
link resolves. ✅

One rule had to be made to agree across the language boundary: `anchor_id` in
`app/knowledge/sites.py` and `anchorId` in `ui/src/app/lib/site.ts` must produce the
same string. The studio stamps those ids onto headings and the linker validates
`[text](#anchor)` links against them, so a divergence — the UI not folding accents,
say — would have reported every accented heading link as dead.

Answered here: open question 3 — Home is **templated from the map**, not written by a
model. A model call would be paid on every nav change to restate facts already held
in structured form, and the result could go stale between calls.

---

## Phase S5 — Staleness and provenance ✅

*The differentiator. Mostly bookkeeping we already collect.*

- [x] **Per-page provenance, surfaced** — "written from these 12 files at commit
      `4065c2f`", collapsed under the page as an audit trail rather than in front of
      it. Names the job and knowledge base too.
- [x] **Per-page staleness** — `knowledge_bases.file_hashes_json` records a content
      digest per file; a new build compares its digests against the ones the page was
      written from and marks only the affected pages `stale`. The page's own banner
      then offers to rewrite exactly that one.
      Deliberately **not** a git diff: uploads and local directories have no commits,
      and a digest map works for all of them.
- [x] **Regeneration as a diff** — `doc_pages.previous_markdown` keeps one generation,
      and the reader offers "what changed?" on any rewritten page. Line-level LCS
      computed in the browser, with unchanged runs collapsed — a regenerated page is
      mostly unchanged, and scrolling past four hundred identical lines to find the
      edit is the thing this exists to prevent.
- [x] **Per-page QA** — `doc_pages.qa_score` / `qa_json`, folded together from QA's
      review and validation results. "7/10, 4 of 5 claims verified" against *this*
      page, not against a twenty-page document.

**Done when** pushing a commit that touches three files marks exactly the pages that
depend on them. ✅

The staleness pass runs at the end of analysis, in `site_planner` — it is the one
point where the new build's digests exist and the merged map does too. A build with
no digests (an older knowledge base) marks nothing: saying nothing beats marking a
whole site stale on the strength of a missing column.

---

## Phase S6 — Export and versions ✅

- [x] **MkDocs / Docusaurus exports finally get what they always wanted** — a real page
      tree and a generated `nav:`. A directory per section, and for Docusaurus a
      `_category_.json` so the sidebar mirrors the site's order rather than the
      alphabetical one it would otherwise invent.
- [x] **Static HTML export** of our own theme, so a site can be published anywhere.
      One inline stylesheet, one file per page, nothing loaded from the network —
      the same constraint the studio has, and a test asserts it.
- [x] **Versions** — `doc_site_versions`, pages keyed by version, a version switcher
      in the UI. A version's pages are ordinary `doc_pages` rows carrying its id, so
      a reader and an export walk the same code either way.
- [x] Plus `markdown`: the page tree as plain files, for anyone who wants none of the
      above.

**Done when** an export produces a buildable site with a correct nav, and a frozen
version stops following the live one. ✅ *Verified against the real API: all four
formats exported, a version cut, and the live/frozen split confirmed.*

Two things fell out of the design rather than being designed:

* **`rewrite_links` is the linker in reverse.** The linker resolves `[[page-slug]]` to
  studio routes because the studio is where pages are read; an export turns those back
  into relative file paths. Safe precisely because the linker already proved every one
  of them resolves — `.md` for MkDocs, no suffix for Docusaurus, `.html` for static.
* **Uniqueness had to become two partial indexes.** A NULL `version_id` does not
  compare equal to itself, so one `UNIQUE(site_id, version_id, section_slug, slug)`
  would silently permit two *live* pages on the same slug — the one thing the whole
  design forbids. `ux_doc_pages_live` and `ux_doc_pages_versioned` split it.

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

## Where this ended up

All six phases are implemented and tested — 339 tests green, including the two that
were already failing before this work began.

The open questions, answered:

1. **Does a section map 1:1 to a `doc_type`?** No — `section_slug` and `doc_type` are
   separate columns, so one section may hold pages of several types.
2. **Can a user reorder or rename nav entries by hand, and does it survive
   re-analysis?** Yes, via `pinned` on both pages and nav entries. A pinned page keeps
   its title and order, and survives falling out of a proposal entirely.
3. **How much of Home is generated versus templated?** Templated, from the map, on
   every read. A model call would be paid on every nav change to restate facts already
   held in structured form — and its output could go stale between calls, which is the
   one thing Home must never do.

**What comes next lives in `COMPOSITION_PLAN.md`** — the site is built, and that plan
is about the cost and legibility of writing into it: one planning call per section
rather than per page, page lengths proportionate to their intent, and live progress
where the work is happening.

Two bugs surfaced on the way that had nothing to do with sites, and both were silent:

* **`SECTION_WRITE` never rendered `$already_written`.** The placeholder abutted the
  next word, so `string.Template` read one identifier `already_writtenContext`, found
  no key for it, and left it verbatim — no writer has ever been told not to repeat the
  other sections. `PromptTemplate.render` now raises on an unsupplied identifier.
* **QA, diagrams and exports all keyed off `doc_type`.** Harmless when a job produced
  one document per type; wrong the moment three pages share a type. All three key on
  `doc_key()` now.
