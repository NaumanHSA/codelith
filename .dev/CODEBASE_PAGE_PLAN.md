# The codebase page — showing what was actually learned

Analysis reads a repository once and stores a great deal. The page that follows it
shows about a tenth of that, and none of the parts that answer *what is this project*.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done · `[-]` deliberately not doing

---

## The gap, measured

One reading of `live-face-capture-sdk`, stored against commit `8f673f6`:

| In the database | On the page |
| --- | --- |
| `architecture_json`, 3 068 bytes: **services, layers, relations, patterns, tech_stack** | **nothing.** Not fetched, not typed, not referenced anywhere in `ui/` |
| 12 narratives, `architecture` alone 3 026 chars | 12 tag chips. The prose is unreadable anywhere in the product |
| Code graph: 42 files, **401 symbols**, 37 imports, **115 calls**, 23 packages | nothing. Only `preflight` and MCP read it |
| 373 code chunks with path and line span | nothing. `/evidence` already resolves a span |
| 20 modules, each with a written summary | a radar of role *counts*; `top_modules` is fetched and used on the chat page only |

`architecture_json` is the one that matters most. It holds `relations` as
`{from, to, kind}` — `src → src.session (calls)`, `src.session → src.camera
(configures)`, `src.camera → src.loop (feeds)` — plus named `layers` and detected
`patterns` (`Web Worker`, `Hybrid Encryption`, `Off-thread Rendering`). That is a
labelled architecture diagram, already computed, sitting unused in a JSON column.

## Two constraints that shape everything below

**The clone is gone.** Analysis discards the checkout, so `code_chunks` is the only
copy of any source. A file viewer can only show what was indexed.

**Chunks do not perfectly tile a file.** Measured on `ort.min.js`: 109 chunks over
2 857 lines with **4 gaps**. So the viewer must show its gaps rather than splice
across them — concatenating chunk 3 onto chunk 2 would render code in an order that
does not exist in the file, which is worse than admitting a gap.

*Building it found the other half of that: chunks also **overlap**.*
`src/loop/livenessLoop.js` is 252 lines whose chunks cover 423, and `server/main.py`
is 158 covered by 236. Concatenation would therefore have doubled code as well as
reordered it. Reconstruction is line-addressed: each chunk writes its own lines into
a map, first writer wins, and every overlap measured agrees exactly.

*And `docstring` chunks must be excluded.* One carries the span of the **symbol** it
describes while holding a two-line summary of it, so writing its text at its declared
start line puts a summary where a function body should be. Eight conflicting lines on
`server/main.py`; zero once only `code` chunks are used.

`[-]` **Storing a second copy of the source** to make the viewer complete. It doubles
what a project costs on disk to fix a cosmetic gap, and the honest label is cheaper.

## Where this belongs

Not in `apps/`. `CLAUDE.md` defines an app by what it *reads from* the knowledge base;
browsing the knowledge base is the base's own reading surface, and it stays on the
project page and in `codelith/api/v1/`. `tests/unit/test_module_isolation.py` must stay
green with no new `KNOWN_LEAKS`.

---

## Phase 1 — The architecture, drawn — **done**

The highest ratio of value to work in the application: the data is computed, stored,
correct, and thrown away.

*Built. `GET /projects/{id}/architecture` reads the newest usable KB through
`ArchitectureService`, whose entire body is coercion and which cannot raise; 22 unit
tests hold the shapes it has to survive. `ArchitectureMap.tsx` lays the services out by
longest path from the roots, with a cycle guard, and draws relations as labelled
curves. Verified against both projects on this machine: 10 services / 8 relations and
7 / 6, no dangling edges either time.*

*Two things the build taught, kept because they will come back:* an edge label at the
straight-line midpoint collides with every other edge between the same two rows, so
labels sit on their own Bezier at alternating t; and a layout by depth needs an
iteration cap, because a model will happily write a cycle into `relations`.

`[x]` **1.1** `GET /projects/{id}/architecture` returning services, layers, relations,
patterns and tech stack from the newest usable KB. A schema, not the raw column: the
JSON was written by a model and needs coercing before a component can trust it.

`[x]` **1.2** Tolerant coercion. A missing key, a relation naming a service that does
not exist, a layer holding modules no longer present — none of these may throw. The
map degrades to what it can show.

`[x]` **1.3** `ArchitectureMap` component: services as nodes, `relations` as labelled
edges, `layers` as bands. Laid out from the data rather than hand-placed, because the
number of services is not known in advance.

`[x]` **1.4** Hovering a service names what it is and what it owns; hovering an edge
says what the relation is. The diagram carries the shape, the caption carries the
sentence.

`[x]` **1.5** Tech stack and patterns as a strip beneath it. Both are single-word
facts that took a quality-tier call to derive and currently reach nobody.

## Phase 2 — The narratives, readable — **done**

*Built. `GET /projects/{id}/narratives` returns the prose in reading order, and the
chips became a rail with the words beside it: 12 topics and 2 234 words on project 1,
10 and 1 691 on project 2.*

*2.3 turned out to need a fix in analysis, not a read.* `KBNarrative.source_refs_json`
is documented as recording "which modules/entities fed the narrative so QA can verify
claims" and stored `{"generated_by": "narrative_writer_agent"}` — a fact about the
writer, not about the codebase. The writer already knew: `_relevant_modules` picks the
shortlist that goes into the prompt and `_facts` picks the entity kinds. Both are now
recorded. The shortlist moved out of `_write` and into the caller so the list recorded
is the same object that went into the prompt rather than a second derivation of it.

Every knowledge base on this machine predates that, so the reader says **"sources not
recorded on this run"** and will keep saying it until those projects are re-analysed.
That is the honest answer: inferring which modules fed a narrative after the fact
would print a citation nobody could check.

`[x]` **2.1** `GET /projects/{id}/narratives` — topics with their prose.

`[x]` **2.2** A reader on the codebase page: the topic chips stop being decoration and
open the 3 000 words behind them.

`[x]` **2.3** Provenance per narrative, the same as a published page: which commit,
which files it was anchored on.

## Phase 3 — The code, at last — **done**

The credibility gap. A product whose claim is that it read the code has never shown
any.

*Built, at `/app/projects/:id/code`. Verified against every file in both knowledge
bases: 60 files rebuilt, every segment contiguous, correctly sized and in order, with
no line appearing twice. The gaps are real and almost always the blank line between
two declarations, which is not a thing worth guessing on a reader's behalf.*

*The tree is the union of `graph_files` and the chunk table, because they disagree:
`graph_files` has language, size and symbols but only for files a provider parsed,
while the chunk table has content for those and for the markdown no parser looked at.
`README.md` exists in one and not the other.*

*Two bugs worth remembering.* The verifier that checks highlight.js output before it
reaches `dangerouslySetInnerHTML` was written as `^(?:<span …>|</span>|[^<>]*)*$` — a
group that can match empty under a `*`, which backtracks exponentially on input that
fails. It did not throw and it did not render wrongly: it pinned the browser's main
thread hard enough that Playwright could not screenshot the page, and it took a
request trace to find. And highlight.js itself takes **24 seconds** on a 360 KB
minified bundle, so the size guard now lives in `highlight.ts` rather than in the one
component that knew about it. `ui/scripts/check-highlight.mjs` runs in the build and
is a clock as well as a correctness test, because a correctness test passed on both.

`[x]` **3.1** `GET /projects/{id}/files` — the indexed tree from `graph_files`, with
language and symbol counts.

`[x]` **3.2** `GET /projects/{id}/files/{path}` — the chunks of one file in order,
each with its span, **and the gaps between them named**. See the constraint above.

`[x]` **3.3** A viewer: tree on the left, code in the middle with real line numbers,
symbols in that file on the right.

`[x]` **3.4** Deep-linkable — `?file=src/x.js#L12-L30` — so Ask-the-code citations and
published pages can point into it.

`[x]` **3.5** Say plainly what is not there: files the analysis skipped, and lines no
chunk covered.

## Phase 4 — Modules, as an explorer rather than a radar — **done**

*Built. `GET /projects/{id}/modules` returns all twenty with their prose, and
`KnowledgeMap.tsx` is deleted rather than demoted: keeping a plot of five role counts
above a list that shows the same distribution in its filter chips would be two
answers to one question.*

*Test modules are returned and flagged.* `list_by_kb` excludes them by default
because its callers build prompts, and a documentation writer should not spend
context on the test suite. A person browsing a codebase is in the opposite position:
"five files, 591 lines" is one of the more useful rows on the page, and dropping it
would be a claim about the project rather than a display choice. The unwritten
summary on a test module is not counted as a gap, because not summarising them is a
decision and reporting a decision as a defect is noise.

`[x]` **4.1** Replace the role radar with a module table: path, role, LOC, and the
summary that was written for each one. The radar shows five numbers; twenty modules
with a sentence each is the thing somebody actually wants.

`[x]` **4.2** Filter by role and language; sort by size.

`[x]` **4.3** A module opens its files in the Phase 3 viewer.

## Phase 5 — The graph, browsable — **done**

*Less new machinery than expected and more plumbing. `PreflightService` already
assembled callers, direct importers, transitive reach with distance, tests, cited
pages and risk. Three things were missing and all three were visibility, not
capability:*

* **`imports` was never computed.** `get_imports` sat on the graph store, reachable
  only through MCP, so a pre-flight could describe everything around a file except
  what it stands on. Now computed in the same graph pass and printed in the brief, so
  `before_edit` gained it too.
* **`dependents` was computed and never rendered.** It has been in `PreflightOut`
  since the endpoint was written, and no screen read it.
* **`weight` never left the process.** `reach_weight` is documented as the ranking
  every caller should sort on and was not on the wire at all.

*And the panel made you type a path first. A question you have to phrase is one
nobody asks, which is the same failure as putting a check behind its own page, so the
graph now sits under whatever file the source viewer has open, asked automatically,
with every path a link back into the viewer. Verified on real data: the graph is
symmetric (A imports B exactly when B is imported by A), and `server/main.py` scores
15 on nothing but the three written pages describing it, which is what `reach_weight`
was for.*

`[x]` **5.1** Who imports this file, what it imports, who calls this symbol. All three
already exist on the graph store and are reachable only through MCP.

`[x]` **5.2** Reach and `reach_weight` from `knowledge/preflight.py`, so "what breaks
if I change this" is answerable in the studio and not only by an agent.

## Phase 6 — Joining it up — **done**

*The whole plan is now complete.*

**6.1** A published site emits a source page per cited file, off a `Source` tab,
using the same reconstruction the studio's viewer shows and drawing gaps as gaps.
Eighteen pages on one project, six on the other, 379 links, none broken.

*The rule that makes it honest is which citations become links.* A written page's
inline code spans are a mixture: real paths, module names (`src.draw`), types
(`Image.Image`), and files that exist in the repository but were never indexed
(`package.json`). Only an exact match against a file the knowledge base can actually
show becomes a link; measured, that is fourteen of twenty-eight spans on one project
and five of ten on the other. Everything else is left exactly as it was, which is the
same rule `rewrite_links` already followed for pages.

**6.2** Deliberately not what the line says. The sources panel had learned to open an
excerpt in place since this was written, and replacing that with a navigation away
from the answer would be a regression: checking a claim you can still see is what the
panel was built for. So the excerpt stays and gains an **open in source** link, with
the cited lines already lit.

**6.3** Drift compares the two maps: services added, removed or retyped; edges added,
removed or reworded. Keyed on the pair rather than the triple, so a verb change reads
as one edge reworded instead of one cut and another opened.

*And `is_empty` was wrong.* It asked only about modules and entities, so a release
that moved no module but rewired two services reported "nothing structural changed"
while the diagram was different.

`[x]` **6.1** Citations in published documentation resolve into the code viewer
(`PUBLISHING_PLAN.md` 6.4).

`[x]` **6.2** Ask-the-code sources open the same viewer rather than their own panel.

`[x]` **6.3** Drift compares two architecture maps: a service that appeared, an edge
that vanished. Two readings and a graph per reading already exist; this is assembly,
and nothing else in the category can do it.

---

## What building it taught

Kept because each of these cost real time to find, and none was visible from the plan.

* **Chunks overlap as well as gap.** The plan recorded the gaps. `livenessLoop.js` is
  252 lines whose chunks cover 423, so concatenation would have doubled code as well
  as reordered it.
* **`docstring` chunks carry the span of the symbol they describe** and two lines of
  summary. Written at their declared start line they put a summary where a function
  body goes.
* **A guard only one caller knows about protects only that caller.** Twice: the
  highlighter's size limit lived in the component, and `coerce` relied on its own
  service checking the column was a dict. Both broke the moment a second caller
  arrived.
* **A correctness test can pass while the feature is unusable.** A catastrophically
  backtracking regex pinned the browser's main thread and threw nothing.
  `check-highlight.mjs` is a clock as well as a checker because of it.
* **Most of what was missing was visibility, not capability.** `imports`,
  `dependents`, `weight`, the narratives, the module summaries, the architecture map:
  analysis had computed all of it and nothing had ever read it.

---

## Risks

- **`architecture_json` is model-written.** Every field is optional in practice.
  Phase 1.2 is not defensive programming for its own sake; it is the difference
  between a map and a crash on somebody's repository.
- **Layout of an unknown graph is the hard part of 1.3.** Services here number six;
  a monorepo might have sixty. The layout has to degrade to something readable rather
  than a hairball, and saying "too many to draw, here is the list" is an acceptable
  answer at some size.
- **Old knowledge bases predate `architecture_json`.** The page must handle its
  absence without looking broken.
