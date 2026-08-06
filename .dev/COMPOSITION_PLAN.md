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

## Phase C1 — Measure what the fix already changed ✅

*No code. One run, and a recorded baseline.*

- [x] Recompose `architecture` as **one section job** (not three page jobs), on the
      restarted worker.
- [x] Record per page: word count, heading count, heading titles.
- [x] Record per stage: wall time, and how many planner calls were made.
- [x] Re-check the shadowing: do `overview`'s headings still map one-to-one onto other
      sections, or does it now defer to them?
- [x] Re-check source overlap between the section's pages.
- [x] Write the numbers into this document beside the pre-fix table.

**Done when** there is a post-fix baseline here, and C4/C5 are sized against it rather
than against a run with a broken prompt. — **Done.**

### C1 results — job #4, 2026-08-06

**Read the caveat first.** This is not a controlled A/B of the `$already_written` fix.
The run is on a rebuilt database with different models (`qwen/qwen3.5-9b` quality,
`liquid/lfm2.5-1.2b` fast) and a freshly planned site map, so `architecture` has **four**
pages rather than three and the page set is not the same. It is a post-fix baseline,
not an isolation of the fix. Where a number below is comparable, it says so.

The overview page is `architecture/overview-2` — `getting-started/overview` claimed the
bare slug first, and page slugs share one namespace site-wide, by design.

**Time — 570s for four pages, as one section job.**

| Stage | Time | |
|---|---|---|
| `kb_loader` | 0.0s | |
| `strategy` | **6.0s** | once per job, as designed |
| `planner` | **187.5s** | **4 calls**, ~47s each — still one per page |
| `writer` | 221.4s | 4 concurrent: 98.6 / 147.6 / 200.4 / 221.4 |
| `linker` | 0.2s | no LLM |
| `diagram` | 0.0s | disabled |
| `qa` | 154.4s | |
| `formatter` + `publisher` | 0.3s | |
| **Total** | **570.1s** | wall clock |

Per page that is 142s, against 140s per page pre-fix — **unchanged**. What did change is
the 72s of redundant `strategy` calls: one section job spends 6.0s where three page jobs
spent three calls. **That saving comes from job scope, not from the prompt fix**, and it
is already available today by composing a section instead of a page.

**The heading cap is not the binding constraint — C5's third bullet is void.**
Every page planned **exactly four `##` headings**, against a `SITE_MAX_HEADINGS_PER_PAGE`
of 6. Cutting that setting to 4 would change nothing, because the planner is already
choosing 4 unprompted.

| Page | Words | `##` | `###` | Words per `##` |
|---|---|---|---|---|
| `architecture/overview-2` | 2,299 | 4 | 13 | 575 |
| `architecture/request-lifecycle` | 2,073 | 4 | 20 | 518 |
| `architecture/state-management` | 2,214 | 4 | 18 | 554 |
| `architecture/data-model` | 2,919 | 4 | 24 | 730 |
| | **9,505** | **16** | **75** | **594** |

Pre-fix `overview` was 2,774 words under five headings — **555 words per heading**. Post-fix
it is 575. The per-heading verbosity did not move. Length is a product of headings ×
~570 words, so **the word budget (C5's second bullet) is the whole of C5's leverage**;
the heading count was never the problem. Note also the 75 `###` subheadings nobody asked
for — the writer is generating a second level of structure on its own initiative.

**The fix is confirmed working, empirically.** The writer emitted **64 `[[ ]]` references**
and every page carries real cross-page links (`[[api/gateway]]`,
`[[getting-started/installation]]`, `[[architecture/state-management]]`). Those addresses
exist nowhere except the neighbour list, so the paragraph reached the model. The
`PromptTemplate` guard in `app/llm/prompts/base.py` now makes the silent-failure mode
impossible anyway: an unsupplied identifier raises instead of rendering as literal text.

**Shadowing — reduced, not resolved.** `overview-2`'s four headings:

```
System Entry Points and Initialization        → partly architecture/request-lifecycle
Core Agent and LLM Abstraction Layer          → agents/*, services/*
Data Access and State Persistence             → infrastructure/vector-stores, architecture/state-management
Tooling, Gateway, Workflow, and Observability → tools/*, api/gateway, infrastructure/observability
```

Pre-fix, five headings mapped one-to-one onto five other sections. Post-fix it is four
headings mapping onto *groups* of sections — broader buckets covering the same ground.
The page is still an overview that summarises the rest of the site rather than pointing
at it. **The instruction is being read and partly obeyed — it links now — but it has not
stopped the page from restating its neighbours.**

**Source overlap — still essentially nil**, confirming the pre-fix finding that pages are
not rewriting the same code. Of 26 cited files across four pages, three are shared:

| Pair | Shared |
|---|---|
| `overview-2` ∩ `request-lifecycle` | 1 — `neurosurfer/app/server/gateway.py` |
| `state-management` ∩ `data-model` | 2 — `agents/context/{durable_state,manager}.py` |
| all other pairs | 0 |

**New defect this run surfaced — dead links in published output.** Of the 64 `[[ ]]`
references, **29 were aimed at source file paths**, which `SECTION_WRITE` explicitly
forbids ("it is not a page and wrapping it in `[[ ]]` just loses you the formatting").
Worse, the writer also emits ordinary markdown links whose href is a source path:

| Page | Links | Resolved | Dead |
|---|---|---|---|
| `architecture/overview-2` | 8 | 8 | 0 |
| `architecture/request-lifecycle` | 9 | 9 | 0 |
| `architecture/state-management` | 7 | 7 | 0 |
| `architecture/data-model` | 28 | 9 | **19** |

All of it is on one page, so this is a drift the writer falls into rather than a
systematic failure — but `data-model` shipped with 68% of its links dead, including
malformed hrefs carrying a stray backtick: `[`TracerConfig`](`neurosurfer/tracing/config.py)`.
Nothing in the pipeline caught it. The linker validates `[[ ]]` addresses and anchor
links; a plain markdown link to a relative path is not checked by anything.

---

## Phase C2 — Progress where the work is happening ✅

*The reader and the operator both need to see the same thing.*

- [x] **Derive "being written" from the server, not local state.** `doc_pages.job_id`
      is already set when a job claims a page, and `SitePage` already exposes it — the
      docs page just is not reading it. A page with `status === 'generating'` shows as
      in-flight however you arrived at it.
- [x] **Poll that job and show real progress** — the same stage narration the jobs
      page uses (`lib/narrate.ts`), not the word "writing…".
- [x] **"View run →"** on the in-progress page, going to the job.
- [x] **Auto-reload on completion** — when the job reaches a terminal status, reload
      the site map and the open page. Sitting on a page waiting is the common case.
- [x] **Job page says what it is writing** — project, doc type, and the page addresses.
      "Architecture · 1 page" does not tell you *which* page, and every run looks alike.
- [x] **Surface a stranded page.** A page left `generating` because its worker died
      currently spins forever. Show it as stalled with a way to retry.

**Done when** starting a write, navigating to Jobs, and coming back shows the same live
progress — and a finished job refreshes the page without a manual reload.

---

## Phase C3 — The reading column ✅

- [x] Move the section nav **inside the centred column**, against the doc container,
      mirroring the heading ToC on the right rather than sitting flush against the
      shell's rail with a gap between.
- [x] **Larger entries** — these are the site's files, and they currently read as
      secondary to the shell navigation beside them.
- [x] Keep the planned-page Generate affordance and the status marks.
- [x] Check the symmetry at `lg` and `xl`, and that it still collapses sanely below.

**Done when** the page list and the heading ToC sit symmetrically either side of the
reading column.

---

## Phase C4 — One plan per section ✅

*The change the pipeline actually wants.*

Today the planner runs **once per page**, and each page is planned seeing only its
neighbours' one-line intents — never their headings. Nothing stops `overview` planning
"LLM Integration Layer" while `llm-stack/providers` independently plans the same
ground. The stage that allocates content cannot see the allocation.

- [x] **New `SECTION_PAGE_PLAN` prompt** — given every page in the section with its
      intent and anchor files, return headings for all of them in one call.
- [x] **`CompositionPlannerAgent` plans per section**, not per page, when the job's
      scope is a section.
- [x] **Validation unchanged** — `key_files` still checked against the whole knowledge
      base, and a hallucinated path still dropped.
- [x] **Fall back to the per-page planner** when the call fails or returns nothing
      usable. A bigger call is a bigger blast radius; the old path stays as the net.
- [x] One artifact per section, so a bad allocation is diffable.
- [x] Tests: one planning call for an N-page section; the fallback fires on a failed
      call; invented paths are still discarded.

**Done when** composing a three-page section makes one planning call, and no page plans
a heading another page in the same section owns.

*Expected saving, sized against C1: **187.5s of planning for a four-page section becomes
one call of roughly 50–70s** — around 120s off a 570s job, or 21%. The coherence still
matters more than the seconds, and C1 raised its price: the anti-duplication instruction
demonstrably reaches the writer now and the overview page **still** covers its
neighbours' ground. Telling a writer not to duplicate cannot fix an allocation that was
already made by four independent planning calls. C4 remains a rescue, not an
optimisation.*

---

## Phase C5 — Pages the size of pages ✅

*Re-scoped after C1. The heading cap was not the cause; per-heading verbosity is.*

- [x] **Reframe `SECTION_WRITE`.** It says *"write ONE section of $doc_type
      documentation"* — the model has no idea it is writing a heading *inside a page*,
      so it writes like a chapter. Say what it is: this page, this heading, these
      neighbours.
- [x] **A word budget per heading**, carried in the prompt. **This is now the whole of
      C5's leverage.** C1 measured 594 words per `##` across four pages, against 555
      pre-fix — the number that has never moved, and the one that sets page length.
- [x] **Bound the `###` level too.** C1 found 75 subheadings across four pages that
      nothing asked for — 19 per page under 4 planned headings. A word budget the model
      answers by fragmenting into more sub-structure has not been obeyed.
- [ ] ~~**`SITE_MAX_HEADINGS_PER_PAGE` 6 → 4.**~~ **Void.** C1 found every page already
      planning exactly 4. The cap is not binding and lowering it is a no-op.
- [x] **An explicit steer for overview-shaped pages** — point at the other pages, do
      not summarise them. This is the page type that goes wrong, and C1 confirms it
      still goes wrong *with* the anti-duplication paragraph rendering. Worth doing, but
      expect C4 to be what actually fixes it.
- [x] **Reject markdown links to source paths.** New in C1: `data-model` published 19
      dead links out of 28, source paths used as hrefs, some with a stray backtick
      inside. The linker checks `[[ ]]` addresses and anchors; nothing checks a plain
      relative-path link. Either validate them or teach the writer to stop — the prompt
      already says to, and was ignored on one page in four.
- [x] Measure again against C1's baseline.

**Done when** a page's length is proportionate to its intent rather than to the number
of headings it was allowed.

---

## Risks, stated plainly

- ~~**C1 may make C4 and C5 much smaller.**~~ **Answered: it did not.** The fix renders,
  the writer links to its neighbours, and `overview-2` still covers their ground in four
  broad headings instead of five narrow ones. C4 stays a rescue. C5 shrank for a
  different reason than expected — its heading-cap bullet turned out to be a no-op,
  leaving the word budget as its only real lever.
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

---

## Results — C2 through C5, job #5, 2026-08-06

Same section, same four pages, same models as C1's job #4, so these are directly
comparable. `page_slugs` had to name the four addresses explicitly rather than the
section: a section scope means *the gaps in it*, and all four were already `ready`.

| | C1 (job #4) | C4+C5 (job #5) | |
|---|---|---|---|
| **Words, total** | 9,505 | **4,996** | **−47%** |
| Words per page | 2,376 | **1,249** | −47% |
| **Words per `##`** | 594 | **312** | **−47%** |
| `##` headings | 16 (4/page) | 16 (4/page) | — |
| `###` subheadings | 75 | **39** | −48% |
| Planner calls | 4 | **1** | C4 |
| Cross-page links resolved | 33 | **40** | +21% |
| **Dead links published** | **19** | **0** | C5 |
| `[[ ]]` aimed at source files | 29 of 64 (45%) | 6 of 46 (13%) | −71% |
| Wall clock | 570.1s | 625.7s | **+10%** |

### C5 worked, and by more than the budget asked for

The budget was 350 words per heading; the result is 312. Page length halved without
touching the heading count — which is the confirmation that C1 read the mechanism
correctly, and that cutting `SITE_MAX_HEADINGS_PER_PAGE` would have fixed nothing.

The overview steer is visible on its own: **`architecture/overview-2` went from 2,299
words with 8 outgoing page links to 1,237 words with 24**. Half the length, three times
the links out. That is the behaviour the page type is supposed to have — naming a
component and sending the reader to its page instead of re-explaining it.

**Dead links went to zero**, from 19. Both halves contributed: the writer aimed far
fewer `[[ ]]` at source paths (45% → 13%), and the linker demoted the 15 markdown links
to source paths that would otherwise have shipped — `data-model` alone had 11. The
guard is doing real work, so the prompt rule alone would not have been enough.

### C4 does save the time — the run that said otherwise was a reasoning loop

**Corrected after investigation.** The stage timings say 187.5s across four calls became
221.3s in one, and this document first concluded C4 had cost time rather than saved it.
That was wrong, and the numbers that disprove it were already in the artifacts.

Replaying both prompts against the same model:

| | prompt | completion | wall |
|---|---|---|---|
| one page (`PAGE_PLAN`) | 5,724 | 5,086 | **49.6s** |
| one section (`SECTION_PAGE_PLAN`) | 5,952 | 6,034 | **58.7s** |

Four page calls is therefore ~198s — which matches job #4's measured 187.4s. One section
call is **58.7s**. That is the ~120s saving the estimate predicted, and rather more.

**The interesting number is 5,086 completion tokens for a single page whose stored plan
is 337 tokens of JSON.** `qwen/qwen3.5-9b` is a reasoning model: it emits roughly
**4,700 tokens of thinking per call regardless of task size**, and the artifact stores
the parsed JSON, so none of it is visible there. That fixed per-call overhead is exactly
what C4 removes — four calls paid it four times.

So why did job #5 take 221.3s? Because on that run the reasoning **looped**. The raw
stream shows the model repeating

```
**Wait, checking the "Overview" content again:**
  * Headings: 1. System Entry Points and Initialization Flow …
```

dozens of times until it hit `LLM_MAX_TOKENS`, returned an empty completion, and was
retried — `_chat_with_retry` allows three attempts with backoff, **all inside one traced
span**, which is why 221s reads as a single slow call. 3 × ~80s of exhausted budget plus
backoff is 221s almost exactly.

Three changes came out of this, all in the tree:

- **`SECTION_PAGE_PLAN` no longer asks the model to verify `key_files` membership.** The
  loop was the model agonising over whether each path appears in the inventory. It does
  not need to: `_validate` drops unknown paths silently, so the prompt now says so and
  tells it to answer in one pass without re-checking itself.
- **`chat_completion` counts `reasoning_content`** and logs
  `llm_thought_but_did_not_answer` when a completion is empty but thinking was not.
  Without it this failure is indistinguishable from a slow endpoint.
- **`LLM_MAX_TOKENS` 8192 → 12288.** With ~4,700 tokens spent thinking before the answer
  starts, 8192 left too little headroom for a section-wide response.

**The lesson is not about C4.** It is that on a reasoning model, per-call overhead is
enormous and invisible: ~4,700 tokens ≈ 46s, paid per call, recorded nowhere. Any future
"is one big call cheaper than N small ones?" question on this stack has the same answer,
and it is not the one the stage timings appear to give.

On coherence: `overview-2` stopped restating its neighbours and started linking to them.
Whether that is C4's allocation or C5's overview steer **cannot be separated from this
run** — both landed together. The way to tell them apart is one page-scoped job, which
uses the per-page planner but keeps the steer.

### What got worse

- **Wall clock is up 10%** (570s → 626s) — but see above: ~160s of job #5's planner
  stage was two reasoning loops that produced nothing, not the cost of the section call.
  On the replayed timings the same job would have been ~465s, **18% faster than C1**.
  The writer stage also rose (221s → 261s) despite producing half the words, with
  finishing times clustered tightly (224–261s) where job #4's were spread (99–221s) —
  that pattern looks like queueing at the endpoint rather than the model working harder,
  and is **not confidently attributable to these changes**. One run each, one machine.
- **`state-management` QA fell 7.0 → 5.0**, the only page that dropped. This is exactly
  the risk the plan named: *"cutting headings to four may make pages thin, and the
  failure mode swaps from padded to sparse, which is harder to notice."* The other three
  rose or held (8→9, 6→7, 8→8), so this is one page rather than a trend, but it is the
  page to look at before lowering `SITE_WORDS_PER_HEADING` any further.

### Still open

`SITE_WORDS_PER_HEADING` (350) and `SITE_MAX_SUBHEADINGS_PER_SECTION` (3) are new
settings, tuned on one run of one section of one repository. They are the first things
to revisit against a different codebase.

---

*C1–C5 are implemented. The measurements above are one run each; every conclusion drawn
from a single pair of runs on one machine deserves the scepticism C1's own caveat asked
for.*
