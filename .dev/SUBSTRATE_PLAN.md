# From Documentation Tool to Code Substrate — Plan

`COMPOSITION_PLAN.md` finished the question *"how do we write into the site
economically?"*. This one asks a different question: **what is the knowledge base
actually for?**

Today it has exactly one consumer. Everything the analysis phase produces —
chunks, modules, symbols, entities, narratives — exists to feed the writer. That is
a renderer, not a product boundary. The phases below make the KB a substrate that
documentation happens to be the first consumer of.

Decisions taken before writing this:

| Question | Answer |
|---|---|
| Build Ask-the-code now? | **No.** Phases K1–K3 are its substrate and are worth building on their own merits. K4 lays the contract and stops there |
| Index READMEs and docstrings? | **Yes, but policy-gated per consumer.** Docs generation stays code-only; retrieval for questions may use prose *as a router* |
| Mermaid or D2? | **D2.** And generated from the graph by a builder, not written by a model |
| Where does language-specific code go? | `app/languages/` — unchanged. Every phase here that touches parsing adds a provider method, never a branch in an agent |
| Graph: fix or delete? | **Fix.** It is already a dependency we ship and run |

---

## What the evidence actually says

Measured against the live `neurosurfer` KB (#2, commit `4065c2fc`, status `ready`):

```
1,146 chunks       all chunk_type='code', all language='python'
45 modules         roles: service 28, api 4, utility 4, cli 3, config 2, data_access 2, schema 1, test 1
3,244 symbols      kind, signature, line range, decorators, visibility
74 entities        route 4, env_var 24, dependency 43, entrypoint 3
12 narratives      architecture, data_model, request_lifecycle, error_handling, …
```

Three findings drive the ordering.

**The graph is empty.** `app/memory/graph_store.py` can write `File`, `DEFINES` and
`IMPORTS`, but nothing in `app/agents/analysis/` calls it — the only references are
`code_understanding.py` and `react_mixin.py`, both legacy. A live Cypher count over
the running Neo4j returns nothing. We run a graph database, ship it in
`docker-compose`, and store no graph in it.

**Nine of thirteen entity kinds are declared and never extracted.**
`app/knowledge/constants.py` defines `datastore`, `external_api`, `service`,
`config_file`, `cli_command`, `scheduled_task`, `event`, `infra_resource`,
`test_suite`. The KB contains four kinds. The missing nine are precisely the ones
that answer *where is data stored*, *what does this talk to*, *what runs on a
schedule*.

**One language.** `registry.for_path()` returns `None` for anything without a
provider, and `python.py` is the only provider. The consequence worth stating
plainly: **document-anything cannot analyse its own studio.** `ui/` is 30-odd
TypeScript files that are invisible to every KB we have ever built.

---

# Part I — The substrate

## Phase K1 — Put something in the graph

**Why.** Four later phases want the same thing and none of them can have it: *what
imports what*, *what calls what*, *what defines what*. Vector search cannot answer
"where is this used" — that is a traversal, not a similarity.

**What.**

- Wire `GraphStore` into the analysis pipeline, written alongside `kb_persister`
  so a KB and its graph are committed together or not at all.
- Nodes: `File`, `Module`, `Symbol`, keyed by `(project_id, commit_sha, path)`.
  Commit-scoped, so two KBs of the same repo do not collide.
- Edges: `IMPORTS`, `DEFINES` today; `CALLS` where the provider can resolve it.
- `LanguageProvider` gains `extract_imports()` and `extract_calls()`. Resolution
  from an imported name to a file is **provider work**, not agent work.
- Delete the graph when its KB is deleted. An orphaned graph is worse than none.

**Measured by.** Node and edge counts per label after an analysis run, recorded in
`stats_json`. Today: 0. A pass means `IMPORTS` edges within an order of magnitude
of the import statements the parser saw, and every edge endpoint resolving to a
real file.

**Risk.** Call-edge resolution in a dynamic language is approximate. Approximate is
fine for *"what might this affect"* and unacceptable for anything presented as
exhaustive — so the API returns edges with a `resolved` confidence and the UI never
claims completeness.

---

## Phase K2 — Extract the nine missing entity kinds

**Why.** The vocabulary already exists and the KB is three-quarters empty against
it. These are cheap to detect and directly answer the questions users ask first.

**What.** Behind `LanguageProvider.detect_entities()` and manifest parsing:

| Kind | Detected from |
|---|---|
| `datastore` | SQLAlchemy models/engines, connection strings, migration dirs, Redis/Neo4j/S3 clients |
| `external_api` | HTTP clients with a base URL, SDK constructors |
| `service` | Long-lived classes wired into DI/startup |
| `config_file` | `.env*`, `*.toml`, `*.ini`, `docker-compose*`, `alembic.ini` |
| `cli_command` | `argparse`/`click`/`typer` registrations, `console_scripts` |
| `scheduled_task` | Celery beat, cron expressions, task decorators |
| `event` | Queue publish/consume sites, pub/sub topics |
| `infra_resource` | Compose services, Dockerfiles, k8s manifests |
| `test_suite` | Test roots, fixtures, markers |

Each carries `source_path` + `source_line` so every one is clickable.

**Measured by.** `entity_kinds` in `stats_json` goes from 4 populated to 13, and a
spot audit of 20 sampled entities finds ≥90% pointing at a real definition.

**Risk.** Over-detection is worse than under-detection — a `datastore` list with
false entries poisons every consumer. Precision over recall; anything uncertain is
dropped, not guessed.

---

## Phase K3 — Index prose, and gate it by consumer

**Why.** Docstrings and READMEs carry intent the AST cannot express. They are also
the most likely thing in the repo to be wrong. Both facts are true at once, so the
answer is a policy, not a yes/no.

**What.**

- Index `docstring`, `markdown` and `comment` chunk types. The column already
  exists and is unused.
- Retrieval takes a **policy**, not a flag:

  | Consumer | Policy |
  |---|---|
  | Documentation generation | **Code only.** Indexing existing docs into the generator risks laundering the repo's README into "generated" documentation — the tool appears to work while having paraphrased the thing it replaced |
  | Question answering (later) | **Prose as router.** Retrieve prose, extract the file/symbol references it names, pull *that code*, answer from code |

- Structural priority, not instructional. Separate pools with fixed token budgets
  (code reserved ~70%), so prose cannot crowd out code however well it matches a
  natural-language query. "Prefer code" in a prompt is a soft constraint that
  degrades under context pressure and is unreliable on the 1.2B fast tier.
- Provenance in the payload, not the preamble:
  `[CODE app/db/session.py:12-40]` vs `[PROSE README.md — unverified]`.
- Downrank prose whose file changed after it was written, using `file_hashes_json`.

**Measured by.** On a fixed question set, the share of retrieved context that is
code never falls below the reserved budget; and a page generated with the docs
policy cites zero prose chunks.

**Risk.** Chunk count roughly doubles, so embedding time and index size grow. Worth
measuring before and after — the analysis phase is already the slow one.

---

## Phase K4 — The Ask-the-code playground (ground only)

**Why.** The feature is deferred; the contract is not. Building K1–K3 without a way
to see what they return means finding out at feature time whether they were any
good.

**What — and explicitly what not.**

- A retrieval function that takes a free-form question and returns *evidence*:
  ranked chunks with provenance, the modules and narratives that matched, and the
  graph neighbourhood of any symbol named.
- A router that decides *module vs narrative vs symbol vs graph* before retrieving.
  This is the piece `SectionContextBuilder` cannot do — it is shaped for "evidence
  for a known doc section", not "what is this person asking about".
- An inspector: a dev-only endpoint plus a CLI that prints what a question
  retrieved and why it ranked. This is the deliverable people will actually use
  while building K1–K3.
- **No chat UI. No conversational agent. No answer synthesis.** The playground
  returns evidence, not prose.

**Measured by.** A set of ~20 real questions about `neurosurfer` (*how is the DB
initialised, where is data stored, what runs on a schedule*), each scored by hand
for whether the retrieved evidence contains what is needed to answer. That number
is the honest predictor of whether the feature is worth building.

---

# Part II — The documentation product

## Phase K5 — TypeScript / JavaScript provider

**Why.** The largest open-source surface, and the one that makes the demo
self-evident: the tool can finally document its own studio. `LanguageProvider` was
built for this and has never been exercised by a second implementation — until it
is, the abstraction is a claim rather than a fact.

**What.** One provider. Symbols, imports, entrypoints, test detection, visibility,
manifest parsing (`package.json`), entity detection (routes, env via
`import.meta.env`/`process.env`). No agent, schema or workflow changes — if any are
needed, the abstraction leaked and that is the finding.

**Measured by.** Analyse this repo with `ui/` included; a KB whose `languages` is
`['python', 'typescript']`, with TS modules carrying roles and symbols. Zero
language-specific code outside `app/languages/`, enforced by a test.

---

## Phase K6 — Provider conformance suite, then Go and Java

**Why.** Adding language three should not re-litigate language two. K5 will surface
the real contract; this freezes it.

**What.** A shared test suite any provider must pass — a fixture repo per language
and identical assertions about symbols, imports, entrypoints and entities. Then Go
and Java against it.

**Measured by.** A new provider passes the suite without changes to the suite.

---

## Phase K7 — Diagrams, in D2, built from the graph

**Why.** Diagrams are disabled (`DIAGRAMS_ENABLED=False`) because generated Mermaid
was unreliable. The cause is structural: Mermaid is ~8 grammars under one name and
models blend them — flowchart arrows inside a `classDiagram`, `end` as a node id,
unescaped parens in labels. Our only validation is a best-effort regex
(`app/tools/mermaid.py:10`).

**What.**

- **Stop asking a model for diagram syntax.** A builder emits D2 from the K1 graph
  and K2 entities. The model chooses the subject and writes the labels; the builder
  guarantees the syntax. Validity *and* groundedness by construction.
- D2 replaces `mmdc` at the render layer. This is a lateral move, not a new class
  of dependency — we already shell out to a Node binary
  (`app/tools/mermaid_render.py:89`) and render server-side. D2 ships as a single
  static binary and has a real parser to validate against.
- **Emit SVG, not PNG.** Smaller in a data URI, crisp at any zoom, and able to
  inherit theme tokens — today's `--background white` is a latent bug for the dark
  variant.
- Free-form generation stays as a fallback for diagrams the graph cannot express,
  with a parse→repair loop rather than best-effort regex.
- Mermaid's native MkDocs/Docusaurus support is not a loss: we ship rendered
  images, and DOCX has no other option anyway.

**Licensing note.** D2 core is MPL-2.0, fine for this project. The TALA layout
engine is proprietary and paid — stay on `dagre`/`elk`.

**Measured by.** Diagrams re-enabled; ≥95% of generated diagrams render without a
repair pass, against the failure rate that caused the flag to be turned off.

---

## Phase K8 — Groundedness as a visible surface

**Why.** For AI-written documentation, *"here is what we could not ground"* is what
makes the rest trustable. We already store `source_files` per page; the claim-level
link is missing.

**What.** Sentence- or paragraph-level provenance captured at write time, surfaced
in the studio as a citation the reader can open, and an explicit list of statements
supported by no chunk. Ties directly to K3's provenance tagging.

**Measured by.** Percentage of paragraphs with at least one grounded citation, per
page, shown in Coverage alongside the existing stale/ready counts.

---

## Phase K9 — Publish back to the repository

**Why.** Exports land in a file today, which makes the tool a place you visit. A PR
makes it part of the workflow.

**What.** Given a connected source, open a branch and a PR with regenerated docs,
using the existing formatters. Diff-aware: only pages whose KB inputs changed.

**Measured by.** A PR raised against `neurosurfer` containing only genuinely
changed pages.

---

## Risks, stated plainly

- **K1 and K2 lengthen the analysis phase**, which is already the slow one. Both
  must report their added wall-clock separately in `stats_json`, and both must be
  skippable.
- **K3 roughly doubles chunk count.** Embedding time and pgvector index size grow
  with it. Measure before committing to it as a default.
- **K5 will find that the abstraction leaks.** That is the point of the phase, but
  it means K5 is the least predictable estimate here.
- **K7 depends on K1.** A graph-driven builder with no graph is just Mermaid with
  different syntax, and would re-introduce exactly the failure we are fixing.
- **Precision beats recall throughout K2.** A confident wrong `datastore` entry
  propagates into docs, diagrams and answers simultaneously.

## Open questions

- Does the graph belong in Neo4j at all, or in Postgres alongside everything else?
  Neo4j is a running service and a compose dependency for what may be a few
  thousand edges. K1 should record the counts; if they stay small, dropping a
  service is worth considering.
- Should entity extraction be LLM-assisted or purely static? Static is
  reproducible and free; LLM-assisted catches idioms a parser misses. Proposal:
  static in K2, and revisit only with evidence of what it missed.
- Is `commit_sha` scoping enough for the graph, or do we need per-KB namespacing
  for two KBs at the same commit?
