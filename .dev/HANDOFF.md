# Handoff — picking this up on another machine

Written 2026-08-06, updated the same day after the work below landed on **`main`**
(the `feat/documentation-sites` branch is merged).

## What landed

`SITE_PLAN.md` phases **S1–S6, all complete**: the product now grows **one
documentation site per project**, a section at a time, instead of emitting one flat
document per composition job. The studio builds, and the whole thing has been run end
to end against a real repository.

Alongside it, a round of studio work: project and job deletion, a jobs list, a
dedicated compose page, and the docs reader's navigation.

Since then: **Windows support** (three defects that stopped the worker executing any
task at all — Phase 7 in [../PROGRESS.md](../PROGRESS.md)) and **all of
`COMPOSITION_PLAN.md`, C1 through C5** — the post-fix baseline, then the two UI phases
and the two pipeline changes, each measured against that baseline. 222 unit tests pass.

## Getting running

```bash
cp .env.example .env          # if you have no .env yet
make infra                    # postgres, redis, minio, neo4j
make migrate                  # through a91b6d47c052
./dev.sh                      # worker AND API on :8000, --reload — see the warning below
cd ui && pnpm install && pnpm dev     # studio on :5173, needs Node >= 20.19
```

Then `scripts/seed_dev.py` for the admin user (`admin@docany.dev` / `admin1234`), and
the test database needs to exist before `pytest tests/integration`:

```sql
CREATE DATABASE documentanything_test;
\c documentanything_test
CREATE EXTENSION IF NOT EXISTS vector;
```

### ⚠️ The Celery worker does not auto-reload

The API runs with `--reload` and picks up changes; **the worker does not**. It cost us
twice in one session — two fixes sat in the tree while four jobs ran the old code, and
the results were measured as if they were current. **Restart the worker after any
change to `app/`**, especially agents, prompts or workflows.

## Where the new work lives

| | |
|---|---|
| Site vocabulary, slug rules, proposal coercion | `app/knowledge/sites.py` |
| ORM: sites, pages, versions | `app/models/site.py` |
| The merge — the piece everything rests on | `app/services/site_service.py` |
| Site planning during analysis | `app/agents/analysis/site_planner.py` |
| Cross-page link resolution (no LLM) | `app/agents/composition/linker.py` |
| Export tree, static HTML | `app/formatters/site_tree.py`, `static_site.py` |
| Reader, compose page, jobs page | `ui/src/app/pages/app/{DocsSitePage,ComposePage,JobsPage}.tsx` |
| Everything derived from the map | `ui/src/app/lib/site.ts` |

Four migrations: `c3f1d0a7b592` (sites/pages) → `e7a2b4c81d33` (job scope) →
`f5c93a1e0b28` (staleness/QA) → `a91b6d47c052` (versions). All round-trip.

## Three things that will bite you if you don't know them

1. **`version_id IS NULL` is the live site.** Every read defaults to it. A frozen
   snapshot leaking into the set that gets written to, merged, or marked stale would be
   silently destructive — which is why uniqueness is two *partial* indexes
   (`ux_doc_pages_live`, `ux_doc_pages_versioned`) rather than one constraint. NULL does
   not equal NULL in SQL.

2. **Slugs are permanent.** `SiteService.merge_proposal` may change a page's title but
   never its slug, and never deletes — a dropped page becomes `orphaned`. The merge is
   dirty-checked so re-analysing an unchanged repo writes nothing at all; if you break
   that, S5's staleness becomes meaningless because every page's `updated_at` churns.

3. **`anchor_id` in `app/knowledge/sites.py` and `anchorId` in `ui/src/app/lib/site.ts`
   must produce identical strings.** The studio stamps those ids onto headings; the
   linker validates `[text](#anchor)` links against them. Change one without the other
   and every accented heading link is reported dead.

## State of the dev database

**Rebuilt from empty on 2026-08-06.** The state described in the original handoff
(project 2, KB 2, jobs #12–#16) was on another machine and does not exist here.

Project **1 · neurosurfer** (`github.com/NaumanHSA/neurosurfer`), analysed at
`4065c2fc` — the same commit:

- Knowledge base `ready` — 45 modules, 74 entities, **1,146 chunks** (the same count the
  previous machine recorded), 255 files, 0 vendored, 0 backslash paths
- Site map: **8 sections, 27 pages**, LLM-planned (not the fallback)
- Written: `architecture/{overview-2,request-lifecycle,state-management,data-model}` —
  4 of 27, all `ready`, QA 6.0–8.0
- Jobs #1–#2 cancelled (the Windows worker bugs below), #3 analysis, #4 the C1 composition

The overview page is `overview-2`: `getting-started/overview` claimed the bare slug
first, and page slugs share one namespace site-wide by design
(`app/knowledge/sites.py`). Models are `qwen/qwen3.5-9b` (quality) and
`liquid/lfm2.5-1.2b` (fast), embeddings `nomic-embed-text-v1.5` at **768** dims.

### ⚠️ Windows: three fixes you are now depending on

If you are on POSIX none of this affects you. On Windows the worker **booted and ran
nothing** before these landed — see Phase 7 in [../PROGRESS.md](../PROGRESS.md):
prefork needs `fork()` (now `worker_pool = "solo"`), `asyncio.get_event_loop()` in the
task entrypoints (now `app/workers/runner.py`), and native `\` paths defeating
`registry.should_skip` so no vendored directory was ever skipped.

## Start here

**C1–C5 are all done.** Measurements are in `COMPOSITION_PLAN.md`, beside the pre-fix
table and each other. Headline: page length halved (2,376 → 1,249 words/page), the
planner makes one call per section instead of one per page, and **published dead links
went from 19 to 0**. Cost: wall clock up 10%.

Three things the next person should know before touching any of it:

1. **A reasoning model charges ~4,700 tokens of thinking per call, whatever you ask
   it.** A single-page plan whose stored JSON is 337 tokens cost 5,086 completion
   tokens. It is invisible in the artifacts, which store the parsed result. This makes
   per-call overhead the dominant cost on this stack — one section call (58.7s) really
   does beat four page calls (~198s), and any future "one big call or N small ones?"
   question has the same answer. It also means a hard prompt can loop in reasoning until
   it hits `LLM_MAX_TOKENS`, return nothing, and be retried three times inside one
   traced span: that is what made job #5's planner read as a single 221s call. Watch for
   `llm_thought_but_did_not_answer` in the logs.
2. **C4 and C5 landed in the same run, so their effects are not separated.**
   `overview-2` stopped restating its neighbours, but whether that is C4's allocation or
   C5's overview steer is unknown. One page-scoped job would tell you: it uses the
   per-page planner and keeps the steer.
3. **`state-management`'s QA fell 7.0 → 5.0** — the only page that dropped, and exactly
   the failure mode C5 predicted for itself ("thin rather than padded, which is harder
   to notice"). Look at that page before lowering `SITE_WORDS_PER_HEADING` below 350.

`SITE_WORDS_PER_HEADING` and `SITE_MAX_SUBHEADINGS_PER_SECTION` are new settings tuned
on one section of one repository. A different codebase is the obvious next test.

The open items are older than this plan: **E2** (diagram opt-in per doc type), **E3**
(Neo4j is built every run and queried never), **E4** (the human-review gate returns
`END` with no checkpointer, so approval cannot resume the graph).

## Loose ends

- `ui_backup/` is still parked and wired to nothing. `CLAUDE.md` says delete it once
  nothing cross-references it; nothing does.
- ~300 pre-existing `ruff` findings across the repo (mostly import ordering). Every file
  touched in this work is clean; the rest was left alone deliberately to keep the diff
  readable.
- **CI and the Dockerfile still pin Python 3.12** while `pyproject.toml` now declares
  `>=3.11` to match the conda env in use. They satisfy the constraint, but the floor is
  never exercised — a 3.12-only construct would pass CI and break local dev. One line
  each in `.github/workflows/ci.yml`, `.gitlab-ci.yml`, `Dockerfile`.
- `CLAUDE.md` still tells you to run `make dev`, which is not a Makefile target.
- `documentation_workflow.py` and the `documents` table are untouched and still work.
  The legacy reader still serves them.
- Open questions are recorded at the foot of both plan documents rather than decided.
