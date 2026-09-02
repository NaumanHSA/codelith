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

## Phase 0 — Clear the desk

Small, known, and carried for weeks. Doing them first means the interesting work does
not start on top of a backlog.

- [ ] **Collapse site sections by default.** The sticky write bar fixed "nobody can find
      the controls"; it did not fix twenty-three expanded page rows. Sections collapsed,
      expand to see pages — the Option A layout already agreed.
- [ ] **Ruff into CI, and fix the workflow while there.** `.github/workflows/ci.yml` is
      `workflow_dispatch`-only *and* lints `app/`, a path that has not existed since the
      rename to `codelith/`. 375 findings, 201 auto-fixable; only 10 are the SQLAlchemy
      `Mapped["Project"]` F821 false positives, all under `codelith/models/`, so one
      per-directory ignore clears the blocker that was thought to be the whole problem.
- [ ] **`diagram` opt-in per doc type.** `graph.add_edge("linker", "diagram")` is
      unconditional. ~64s, ~15% of a run, on every composition.
- [ ] **Refresh `STATUS.md`.** It does not know about the compose merge, the review gate
      fixes, or `enigma`. Its own first line asks to be corrected.

## Phase 1 — The CLI

The entry point the landing page already advertises. Against the existing server stack —
no new storage work yet, so this ships fast and is useful immediately.

- [ ] `[project.scripts] codelith = "codelith.cli:main"` and a `codelith/cli/` package.
- [ ] `codelith analyse <path|url>` — start an analysis, stream stage progress, exit
      non-zero on failure. The stage narration already exists in the studio; reuse the
      vocabulary so the CLI and the UI describe a run identically.
- [ ] `codelith ask "<question>"` — one grounded answer with citations, to stdout.
- [ ] `codelith status` — what has been analysed, with commit and size.
- [ ] `codelith studio` — open the UI, starting it if it is not running.
- [ ] `codelith doctor` — check the config: can it reach the database, the model
      endpoint, and is `VECTOR_DIMENSIONS` consistent with the embedding model. That last
      one has already cost a debugging cycle; it fails deep inside ingestion and the fix
      is destructive.
- [ ] Human-readable by default, `--json` for scripting.

**Done when** the landing page's hero command runs.

## Phase 2 — Solo mode

One person, one machine, no containers. The phase this whole plan is for.

- [ ] **Storage profile.** A single setting — `CODELITH_PROFILE=solo|server` — that
      selects the implementations below. Chosen once at startup, never branched on
      per-call.
- [ ] **SQLite + `sqlite-vec`** behind `memory/vector_store.py`. The Postgres path is one
      `ORDER BY embedding <=> :q`; the SQLite path is the same query through a different
      operator. `models/chunk.py` needs the column type to vary by profile.
- [ ] **The code graph in SQL.** `memory/graph_store.py` is the only Neo4j importer, and
      only three tools query it — `find_callers`, `find_dependents`, `blast_radius`. Two
      tables and two recursive CTEs replace a service.
- [ ] **In-process cancellation** behind `core/cancellation.py`, replacing the Redis
      flag. Same `CancellationToken` contract; the long-running work must not notice.
- [ ] **Filesystem storage** behind `storage/s3.py`, under a per-project directory.
- [ ] **Inline execution** instead of Celery: the six `.delay()` sites run the coroutine
      directly with a progress callback. The studio's job rows still get written, so the
      UI works unchanged if somebody opens it.
- [ ] **Alembic against SQLite** — the migrations use `postgresql` dialect features in at
      least two places (`0001_initial_schema.py` and the vector resize). Either branch
      them or generate the solo schema from the models.
- [ ] **A test that keeps the seam honest.** `tests/unit/test_storage_profiles.py`: the
      two profiles must satisfy the same interface, and nothing outside the five seam
      modules may import `neo4j`, `boto3`, `redis`, or `celery`. Modelled on
      `test_module_isolation.py` — a rule enforced by a test, not by intention.

**Done when** `pipx install codelith && codelith analyse .` works on a machine with
Docker uninstalled, and the integration suite passes under both profiles.

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
