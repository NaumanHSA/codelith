# Codelith — the road to something people can actually try

*Written 2 September 2026, against `feat/review-gate`. One phase at a time; tick as
they land. When a phase is done, say what it cost and what it taught, then move on.*

---

## The problem this plan exists to solve

The architecture is good and almost nobody will ever see it.

To evaluate Codelith today, a stranger must clone the repository, install Docker, bring
up **six containers** — postgres, redis, neo4j, minio, prometheus, grafana — copy
`.env`, run migrations, seed a user, install pnpm, start a Vite dev server, *and* have
LM Studio running with three specific models loaded. Nobody does that out of curiosity.

Meanwhile the landing page's hero terminal reads:

```
$ codelith analyse github.com/acme/neurosurfer
```

**That CLI does not exist.** The front page promises the one thing that would make the
product shareable.

So the next stretch of work is not a feature. It is closing the distance between what
Codelith is and what somebody can get to in one command.

## The bet

**`pipx install codelith` → `codelith analyse .` → `codelith mcp`.**

Zero infrastructure for one person on one machine. The server stack stays exactly as it
is for teams; solo mode is the on-ramp, not a replacement.

And a repositioning that costs nothing to state and changes what the project *is*:

> Coding agents re-derive an understanding of your repository by grepping, from scratch,
> every session. Codelith reads it once and serves it.

That sentence is already in `README.md`, at line 182. It should be the first thing
anybody reads.

## Why this is feasible — measured, not hoped

Six containers suggests six deep couplings. It is not what the code says. Counted on
2 September 2026:

| Service | Files that import it | Where |
|---|---|---|
| **Neo4j** | **1** | `memory/graph_store.py` |
| **S3 / MinIO** | **1** | `storage/s3.py` |
| **Redis** | **1** | `core/cancellation.py` |
| **pgvector** | **2** | `memory/vector_store.py`, `models/chunk.py` |
| **Celery** | 6 dispatch sites | 5 files, all `.delay()` |

Every external service is already behind exactly one module. That is not an accident —
it is what "all DB access goes through repositories" and "the graph is a pure function
from files to a graph" bought. Solo mode is a substitution behind five seams, not a
rewrite.

`knowledge/graph.py` says so in its own docstring: *"the whole thing is testable without
Neo4j and without a repository: it is a pure function from files to a graph."*

---

## Phase 0 — Clear the desk ✅

*Done 2 September 2026. Two of the four items were not what the plan said they were.*

- [x] **Collapse site sections by default.** Section headers now carry the counts
      (`3/4 · 1 to write`) so the whole map is scannable without opening anything; a
      section still being written opens itself. The map went from ~2,000px to 1,067px.
- [x] **Ruff into CI, and the workflow fixed.** 373 findings → **zero**. The workflow was
      broken in three ways, not one: `workflow_dispatch`-only so it never ran, linting
      `app/` which has not existed since the rename, and pinned to Python 3.12 while the
      project declares `>=3.11`. All three fixed; it now runs on push and pull request.
      `E501` (143 long lines) is on the ignore list with a note — everything else is
      enforced. Six violations needed judgement rather than `--fix`, including a bare
      `except` in tracing that also swallowed `KeyboardInterrupt`.
- [x] **`include_diagrams` honoured.** Recorded as "`diagram` opt-in per doc type, 64s,
      ~15% of a run" — and that measurement predates `DIAGRAMS_ENABLED` defaulting to
      false. Model-written diagrams have been off for some time; the stage costs seconds.
      The real defect was different and worse: `include_diagrams` had been in `JobConfig`
      since the beginning and **nothing ever read it**. The API accepted the flag, the
      studio sent it, every run drew diagrams anyway.
- [x] **`STATUS.md` refreshed** — 120 commits, 818 unit and 166 integration passing, 13
      migrations, 53 routes, ruff clean.

**Found while working, and fixed:**

- Both `test_the_ui_knows_every_*_stage` integration tests read `narrate.ts` with the
  platform encoding, so they crashed on Windows before asserting anything. They have
  never run on this machine.
- `Toc.tsx` keyed its list on `id + text`, which collides when a page has two headings
  with the same words — ordinary prose, reported by React as duplicate keys.

**Found while working, and recorded rather than fixed** (both now in `STATUS.md`):

- The anchor those duplicate headings share is a real bug, not just a key: both
  table-of-contents entries jump to the first heading. Fixing it means agreeing a
  de-duplication rule across three places that must produce identical strings.
- The stage-coverage tests are far weaker than their docstrings claim — they assert one
  string is present, not that every graph node is narrated.

## Phase 1 — The CLI ✅

*Done 2 September 2026. The landing page's hero command runs.*

- [x] `[project.scripts] codelith = "codelith.cli:run"` and a `codelith/cli/` package —
      `argparse`, `rich` and `httpx`, all of which the project already depended on. A
      command meant to be the recommended way in should not make the install heavier.
- [x] `codelith analyse <path|url>` — resolves a path or a bare `github.com/acme/repo`,
      creates the codebase, starts the analysis and narrates each stage as it lands.
      Verified end to end against a real repository: 9m 19s, exit 0.
- [x] `codelith ask "<question>"` — streams a grounded answer token by token, then the
      sources, and says out loud when a citation was stripped.
- [x] `codelith status` — a table of what has been analysed, with commit and page count.
- [x] `codelith studio` — opens the UI, warning first if the API is not answering.
- [x] `codelith doctor` — server, credentials, all three model tiers, and the
      **embedding dimension measured against the endpoint** rather than trusted from
      config. That mismatch does not fail at startup; it surfaces deep inside ingestion
      and the fix truncates `code_chunks` and re-ingests everything.
- [x] `codelith login`, storing a token under `~/.codelith` at `0600`, with
      `CODELITH_TOKEN` and `CODELITH_API_URL` for CI and shared machines.
- [x] Human-readable by default, `--json` for scripting — and a test that pins the
      contract, because `codelith status --json | jq` breaks the moment one stray line
      of prose lands on the same stream.

21 tests, all of them on the decisions the CLI makes before it calls anything: what a
target means, which codebase was meant when none was named, and the `--json` promise.

**Found while working, and fixed:**

- The CLI printed a replacement character in every truncated cell on Windows. The
  output uses `▸`, `·` and rich truncates with `…`; the console is cp1252. Both streams
  are reconfigured to UTF-8 before anything is written.
- `JobStepOut` serialises `agent_name` under the alias `name`, so following a job
  crashed with `KeyError` the first time it was run for real. It now accepts either,
  which also means it works against an older server.

**Deliberately not done:** the CLI still needs a server running. That is what it is —
a client, so that there is exactly one place a project is created or a question is
answered. Phase 2 removes the requirement for the single-machine case rather than
duplicating the service layer here.

## Phase 2 — Solo mode 🟨 *in progress*

One person, one machine, no containers. The phase this whole plan is for.

**Decided by measurement, not by plan: solo mode needs no `sqlite-vec`.**

The plan assumed a vector extension. Before adding a native dependency, brute-force
exact cosine was measured on 768-dimension vectors:

| chunks | per query | memory |
|---|---|---|
| 1,692 — a 257-file repository | **0.62 ms** | 5 MB |
| 10,000 | 0.76 ms | 31 MB |
| 50,000 — a large repository | **3.0 ms** | 154 MB |
| 200,000 | 10.5 ms | 614 MB |

Faster than the round trip to a database that could do it, **exact** where HNSW is
approximate, and numpy is already a dependency. A local install that needs a compiled
SQLite plugin is one that fails on somebody's machine, and this avoids that entirely.
The ceiling is memory rather than time, and one machine reading one repository is
nowhere near it.

- [x] **Storage profile.** `CODELITH_PROFILE=server|solo`, validated by pydantic so a
      typo fails at startup rather than somewhere deep. Read once to choose
      implementations, never branched on per call.
- [x] **Vector search without pgvector.** The filters stay in SQL — they are what makes
      the query selective — and only the ranking moves. Postgres orders by `<=>` in the
      database; anything else brings the filtered rows back and ranks them exactly.
      **Chosen by the dialect of the bound connection, not by the profile setting**: a
      SQLite database cannot order by cosine distance whatever the configuration
      claims, and a flag that disagreed with the connection would fail at query time
      with an error about a missing operator. 10 tests, including one that pins the
      numpy path against a plain-Python cosine over 200 random vectors.
- [ ] **The code graph in SQL.** Two tables and two recursive CTEs replace a service.
      *Prepared:* the interface can now be implemented by something that is not Neo4j.
      Three callers outside the store — the diagram agent twice and the grounding code
      once — ran raw Cypher, which made the graph the one storage engine whose query
      language had leaked into agents. They are `get_files`, `get_import_edges` and
      `get_packages` now, and a test fails if Cypher appears outside the store again.
      What remains is the SQL implementation itself and choosing between the two by
      profile.
- [ ] **In-process cancellation** behind `core/cancellation.py`, replacing the Redis
      flag. Same `CancellationToken` contract; the long-running work must not notice.
- [ ] **Filesystem storage** behind `storage/s3.py`, under a per-project directory.
- [ ] **Inline execution** instead of Celery: the six `.delay()` sites run the coroutine
      directly with a progress callback. The studio's job rows still get written, so the
      UI works unchanged if somebody opens it.
- [x] **`aiosqlite`** — the one package solo mode genuinely adds. The vector search it
      also needs is numpy, which was already here.
- [x] **The schema builds on SQLite.** All 23 tables. Two column types were the whole
      problem and both are now in `codelith/db/types.py`: `embedding_column` gives
      `vector(768)` on Postgres and packed float32 bytes elsewhere, and `json_column`
      gives `JSONB` on Postgres and `JSON` elsewhere. Twenty model columns named
      `postgresql.JSONB` directly — not only the migrations — and SQLite could not
      compile any of them.

      **The Postgres DDL is byte-identical**: `details JSONB`, `embedding VECTOR(768)`,
      exactly as before. So this needs no migration, existing databases are untouched,
      and the 166 integration tests still pass against real Postgres.

      Proven end to end: 300 chunks written to a SQLite file, embeddings round-tripping
      as `list[float]` of 768 dimensions, and a search returning the planted nearest
      vector first. Semantic search on one machine with no Postgres, no pgvector and no
      compiled extension.
- [ ] **Alembic against SQLite.** The models now build the schema; the *migration chain*
      still does not run there. Four places are Postgres-only — `CREATE EXTENSION
      vector`, the `Vector(dims)` column, the HNSW index, and a `TRUNCATE` in the resize
      migration. **Open question 1 is answered: share the schema and branch at those
      four points**, rather than keeping two schemas in step forever.
- [x] **A test that keeps the seam honest.** `tests/unit/test_storage_seams.py`.
      Each external service has exactly one door — Neo4j, boto3, redis and Celery are
      each imported by a single module — and Cypher may not appear outside the graph
      store. Nothing enforced that before; it was a happy consequence of "all DB access
      goes through repositories", and a happy consequence is not a guarantee. The
      second file to `import boto3` is the one that turns filesystem storage from a
      swap into a refactor, and it always looks reasonable in review. Verified to bite
      by adding a violation and watching it fail.

**The risk to watch.** A second-class path rots. Solo mode must be the profile the
maintainer uses daily, or it will be broken and nobody will know.

## Phase 3 — MCP as the headline

The best pitch in the repository, currently a footnote gated behind `PYTHONPATH="."` and
six containers.

- [ ] **`codelith mcp`** as a first-class command, so `.mcp.json` is
      `{"command": "codelith", "args": ["mcp"]}` rather than a Python module path plus an
      environment variable.
- [ ] **Port to `mcp>=2.0`.** The pin exists because 2.0 removed the
      `@server.list_tools()` / `@server.call_tool()` decorators `codelith/mcp/server.py`
      is built on. Deferred for want of a client to verify against — Phase 1 gives us
      one, and the pin has been load-bearing for long enough.
- [ ] **Lead the README with it.** The current opening sells documentation, which is the
      least differentiated thing here. The knowledge base is the moat.
- [ ] **A one-command install** for Claude Code and Cursor, verified end to end against a
      real editor session, with the transcript in the README.

## Phase 4 — Drift

The first app that exploits something no competitor has: a *structured snapshot of the
code, keyed by commit*. `uq_kb_project_commit` has been in the schema since the
beginning and nothing has ever used it for this.

- [ ] Analyse at two commits, diff the two knowledge bases: modules added, removed,
      re-shaped; entities whose signature moved.
- [ ] Map the diff onto written pages — which pages cite code that has changed.
- [ ] Report it as prose a person can act on: *"`auth.py` gained two routes and lost one.
      These four pages describe the old shape; here is the sentence in each that is now
      wrong."*
- [ ] One entry in `apps/registry.py`, one page. **If this needs a change to an analysis
      agent, stop** — it is asking for something the knowledge base should hold for
      everyone.

This is also the answer to *"why keep old knowledge bases around"*, which is currently an
open question in the schema with no feature behind it.

## Phase 5 — Agent pre-flight

The repositioning, made concrete. `find_callers`, `find_dependents` and `blast_radius`
already exist and are already exposed over MCP. What is missing is the framing.

- [ ] One MCP tool an agent calls **before** editing: given a symbol or file, return what
      it touches — callers, dependents, whether they are tested, and which written pages
      cite it.
- [ ] Make Quality's blast-radius ranking usable outside its own page. That work is on
      `feat/qa` and this is the reason to bring it back.

Codelith stops being "a thing that reads your code" and becomes **the memory and safety
layer for coding agents.** Same substrate. Much larger claim, and one the architecture
already supports.

---

## Deliberately not in this plan

| | Why |
|---|---|
| **Quality's return from `feat/qa`** | Built and parked. Un-parking adds a third app to a product nobody can install yet. Phase 5 is the reason to bring it back, not before. |
| **More document types** | Documentation is the least differentiated thing here. Every tool ships an AI docs generator; none of them ship the knowledge base. |
| **Jobs stuck `running` after a hard kill** | Their pages stay claimed. Telling "abandoned" from "running on another worker" needs a lease or heartbeat, and guessing wrong kills live work. Real, and larger than it looks. |
| **Dark theme** | Tokens are structured for it; components have never been checked against it. Cheap to do, and it changes nothing about whether anybody can run the thing. |
| **Hosted / multi-tenant anything** | The claim is that nothing leaves the machine. That claim has already vetoed features and should keep doing so. |

## Open questions

1. **Does solo mode share the schema with server mode, or diverge?** Sharing means
   Alembic has to speak both dialects. Diverging means two schemas to keep in step.
   Leaning towards sharing, with the model layer branching on profile — but this is the
   decision Phase 2 turns on, and it should be made before any code is written.
2. **Does `codelith analyse .` need a git repository?** Ingestion takes a branch, not a
   revision, and the KB is keyed by commit SHA. A plain directory has no SHA, and the
   commit key is what Phase 4 depends on.
3. **Does the studio ship inside the wheel?** A built `ui/dist` served by FastAPI makes
   `codelith studio` work with no Node at all — at the cost of a much larger package and
   a build step in the release.
