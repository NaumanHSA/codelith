# Composing Into the Site — Plan

The site exists (`SITE_PLAN.md`, phases S1–S6). This is the follow-on: making the
act of **writing into it** economical to run and legible to watch.

Decisions taken before writing this:

| Question | Answer |
|---|---|
| New document or extend `SITE_PLAN.md`? | **New.** That one is a finished record of building the site; this is about the cost and legibility of filling it |
| Redesign the planner first, or measure first? | **Measure.** A bug that suppressed the anti-duplication instruction was live for every run we have data from |
| Scope a shared plan to the doc type or the section? | **The section.** It is the unit people compose in, and a whole-doc-type call risks a truncated response |

---

## What the evidence actually says

Four real runs against `neurosurfer` (jobs #13–16), composing Architecture one page
at a time.

**Time — 419s for three pages.**

| Job | Page | strategy | planner | writer | qa | total |
|---|---|---|---|---|---|---|
| #14 | `architecture/overview` | 17s | **57s** | 47s | 11s | 132s |
| #15 | `architecture/request-lifecycle` | 23s | **50s** | 27s | 54s | 154s |
| #16 | `architecture/data-model` | 32s | **41s** | 44s | 16s | 133s |

Strategy is already once per *job*, so two of those three calls — 72s — bought
nothing. That is a UI default choosing page scope, not a pipeline flaw.

**Duplication — real, but not where it looks.** Source overlap between the three
pages is essentially nil: `overview` cites 15 files, `request-lifecycle` 10, and they
share **zero**; `overview` and `data-model` share one. The pages are not rewriting the
same code.

The overlap is *topical*, and it is bigger than Architecture. `overview` came out at
**2,774 words under five headings**, and every heading shadows a different section of
the site:

```
Entry Points and API Surface     →  architecture/request-lifecycle
Agent Execution Graph            →  agents-graph/graph-engine
LLM Integration Layer            →  llm-stack/providers
Tools and Data Access            →  tools/builtin-overview
Observability and Configuration  →  observability/tracing, configuration/*
```

A page whose intent was *"describes the high-level component structure and service
roles"* became a shallow second copy of twenty other pages.

**And the instruction against exactly that never ran.** `$already_written` — the
paragraph naming every neighbouring page and saying *do not restate them* — abutted
the next word in the template, so `string.Template` read one identifier and left it
unsubstituted. Fixed at 20:51; the worker was restarted at 21:26. **Every run we have
measurements from predates both.** The largest suspected contributor has never been
tested.

That is why C1 comes first.

---

## Phase C1 — Measure what the fix already changed

*No code. One run, and a recorded baseline.*

- [ ] Recompose `architecture` as **one section job** (not three page jobs), on the
      restarted worker.
- [ ] Record per page: word count, heading count, heading titles.
- [ ] Record per stage: wall time, and how many planner calls were made.
- [ ] Re-check the shadowing: do `overview`'s headings still map one-to-one onto other
      sections, or does it now defer to them?
- [ ] Re-check source overlap between the section's pages.
- [ ] Write the numbers into this document beside the pre-fix table.

**Done when** there is a post-fix baseline here, and C4/C5 are sized against it rather
than against a run with a broken prompt.

---

## Phase C2 — Progress where the work is happening

*The reader and the operator both need to see the same thing.*

- [ ] **Derive "being written" from the server, not local state.** `doc_pages.job_id`
      is already set when a job claims a page, and `SitePage` already exposes it — the
      docs page just is not reading it. A page with `status === 'generating'` shows as
      in-flight however you arrived at it.
- [ ] **Poll that job and show real progress** — the same stage narration the jobs
      page uses (`lib/narrate.ts`), not the word "writing…".
- [ ] **"View run →"** on the in-progress page, going to the job.
- [ ] **Auto-reload on completion** — when the job reaches a terminal status, reload
      the site map and the open page. Sitting on a page waiting is the common case.
- [ ] **Job page says what it is writing** — project, doc type, and the page addresses.
      "Architecture · 1 page" does not tell you *which* page, and every run looks alike.
- [ ] **Surface a stranded page.** A page left `generating` because its worker died
      currently spins forever. Show it as stalled with a way to retry.

**Done when** starting a write, navigating to Jobs, and coming back shows the same live
progress — and a finished job refreshes the page without a manual reload.

---

## Phase C3 — The reading column

- [ ] Move the section nav **inside the centred column**, against the doc container,
      mirroring the heading ToC on the right rather than sitting flush against the
      shell's rail with a gap between.
- [ ] **Larger entries** — these are the site's files, and they currently read as
      secondary to the shell navigation beside them.
- [ ] Keep the planned-page Generate affordance and the status marks.
- [ ] Check the symmetry at `lg` and `xl`, and that it still collapses sanely below.

**Done when** the page list and the heading ToC sit symmetrically either side of the
reading column.

---

## Phase C4 — One plan per section

*The change the pipeline actually wants.*

Today the planner runs **once per page**, and each page is planned seeing only its
neighbours' one-line intents — never their headings. Nothing stops `overview` planning
"LLM Integration Layer" while `llm-stack/providers` independently plans the same
ground. The stage that allocates content cannot see the allocation.

- [ ] **New `SECTION_PAGE_PLAN` prompt** — given every page in the section with its
      intent and anchor files, return headings for all of them in one call.
- [ ] **`CompositionPlannerAgent` plans per section**, not per page, when the job's
      scope is a section.
- [ ] **Validation unchanged** — `key_files` still checked against the whole knowledge
      base, and a hallucinated path still dropped.
- [ ] **Fall back to the per-page planner** when the call fails or returns nothing
      usable. A bigger call is a bigger blast radius; the old path stays as the net.
- [ ] One artifact per section, so a bad allocation is diffable.
- [ ] Tests: one planning call for an N-page section; the fallback fires on a failed
      call; invented paths are still discarded.

**Done when** composing a three-page section makes one planning call, and no page plans
a heading another page in the same section owns.

*Expected saving: ~148s of planning for a three-page section becomes ~70s. The
coherence matters more than the seconds.*

---

## Phase C5 — Pages the size of pages

- [ ] **Reframe `SECTION_WRITE`.** It says *"write ONE section of $doc_type
      documentation"* — the model has no idea it is writing a heading *inside a page*,
      so it writes like a chapter. Say what it is: this page, this heading, these
      neighbours.
- [ ] **A word budget per heading**, carried in the prompt.
- [ ] **`SITE_MAX_HEADINGS_PER_PAGE` 6 → 4.** Five headings at ~550 words is how
      `overview` reached 2,774.
- [ ] **An explicit steer for overview-shaped pages** — point at the other pages, do
      not summarise them. This is the page type that goes wrong.
- [ ] Measure again against C1's baseline.

**Done when** a page's length is proportionate to its intent rather than to the number
of headings it was allowed.

---

## Risks, stated plainly

- **C1 may make C4 and C5 much smaller.** If the `$already_written` fix alone stops the
  shadowing, the planner change becomes an optimisation rather than a rescue — and
  should be judged as one. Running C1 first is the only way to know.
- **A section-level plan is a bigger blast radius.** One bad call currently costs one
  page's structure; after C4 it costs a section's. The fallback is not optional.
- **Cutting headings to four may make pages thin.** The failure mode swaps from padded
  to sparse, which is harder to notice. Measure, do not assume.
- **Polling per page adds requests.** One poll per in-flight page, stopped on terminal
  status — but it needs the same discipline `useJob` already has, or the docs page
  quietly becomes a request generator.

## Open questions

1. Should the **UI default to section scope**? Page-at-a-time is what made three
   strategy calls out of one job's worth of work. A "write this page" button that
   quietly composes the section would be wrong; a clearer default might not be.
2. Should **Home be a real page rather than a derived index**, given that the model
   keeps trying to write one? Today `site_planner` is told not to propose one and Home
   is templated — but `architecture/overview` became the overview page anyway.
3. Should **QA run per section** rather than per page? Three reviews of three related
   pages cannot see each other, which is the same blindness C4 fixes for planning.

---

*Nothing in this document is implemented. Phase C1 is the next piece of work, and it
is a measurement, not a change.*
