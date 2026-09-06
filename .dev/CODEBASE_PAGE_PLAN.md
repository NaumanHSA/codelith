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

## Phase 3 — The code, at last

The credibility gap. A product whose claim is that it read the code has never shown
any.

`[ ]` **3.1** `GET /projects/{id}/files` — the indexed tree from `graph_files`, with
language and symbol counts.

`[ ]` **3.2** `GET /projects/{id}/files/{path}` — the chunks of one file in order,
each with its span, **and the gaps between them named**. See the constraint above.

`[ ]` **3.3** A viewer: tree on the left, code in the middle with real line numbers,
symbols in that file on the right.

`[ ]` **3.4** Deep-linkable — `?file=src/x.js#L12-L30` — so Ask-the-code citations and
published pages can point into it.

`[ ]` **3.5** Say plainly what is not there: files the analysis skipped, and lines no
chunk covered.

## Phase 4 — Modules, as an explorer rather than a radar

`[ ]` **4.1** Replace the role radar with a module table: path, role, LOC, and the
summary that was written for each one. The radar shows five numbers; twenty modules
with a sentence each is the thing somebody actually wants.

`[ ]` **4.2** Filter by role and language; sort by size.

`[ ]` **4.3** A module opens its files in the Phase 3 viewer.

## Phase 5 — The graph, browsable

`[ ]` **5.1** Who imports this file, what it imports, who calls this symbol. All three
already exist on the graph store and are reachable only through MCP.

`[ ]` **5.2** Reach and `reach_weight` from `knowledge/preflight.py`, so "what breaks
if I change this" is answerable in the studio and not only by an agent.

## Phase 6 — Joining it up

`[ ]` **6.1** Citations in published documentation resolve into the code viewer
(`PUBLISHING_PLAN.md` 6.4).

`[ ]` **6.2** Ask-the-code sources open the same viewer rather than their own panel.

`[ ]` **6.3** Drift compares two architecture maps: a service that appeared, an edge
that vanished. Two readings and a graph per reading already exist; this is assembly,
and nothing else in the category can do it.

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
