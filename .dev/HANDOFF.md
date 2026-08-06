# Handoff — picking this up on another machine

Written 2026-08-06. Everything below is on branch **`feat/documentation-sites`**.

## What landed

`SITE_PLAN.md` phases **S1–S6, all complete**: the product now grows **one
documentation site per project**, a section at a time, instead of emitting one flat
document per composition job. 339 tests pass, the studio builds, and the whole thing
has been run end to end against a real repository.

Alongside it, a round of studio work: project and job deletion, a jobs list, a
dedicated compose page, and the docs reader's navigation.

`COMPOSITION_PLAN.md` (phases **C1–C5**) is the next body of work. **Nothing in it is
implemented.** C1 is a measurement, not a change, and it should be done first — see
below.

## Getting running

```bash
cp .env.example .env          # if you have no .env yet
make infra                    # postgres, redis, minio, neo4j
make migrate                  # through a91b6d47c052
make dev                      # API on :8000, --reload
make worker                   # separate terminal — see the warning below
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

Project **2 · neurosurfer** (`github.com/NaumanHSA/neurosurfer`), analysed at
`4065c2fc`:

- Knowledge base 2, `ready` — 45 modules, 74 entities, 1,146 chunks, 12 narratives
- Site map: **8 sections, 23 pages**, LLM-planned (not the fallback)
- Written: `getting-started/{installation,cli-usage}` and
  `architecture/{overview,request-lifecycle,data-model}` — 5 of 23
- Jobs #12 (analysis) through #16 (compositions)

**Those five pages were written before two prompt fixes landed.** Treat their word
counts and overlap as pre-fix data — that is precisely what C1 exists to re-measure.

## Start here

**C1, from `COMPOSITION_PLAN.md`.** Recompose `architecture` as *one section job* on a
restarted worker, and record what comes out.

The reason it is first: every measurement in that plan comes from runs where
`$already_written` — the paragraph naming every neighbouring page and saying *do not
restate them* — never rendered. `string.Template` read `$already_writtenContext` as one
identifier, found no key, and left it verbatim. It is fixed, but untested. If that
alone stops `architecture/overview` from shadowing five other sections, then C4 (one
plan per section) is an optimisation worth ~80s rather than a rescue, and C5's heading
cut risks making pages thin instead of fixing them.

Measure first. Then C2/C3 (UI, independent, low risk), then C4/C5 sized against real
post-fix numbers.

## Loose ends

- `ui_backup/` is still parked and wired to nothing. `CLAUDE.md` says delete it once
  nothing cross-references it; nothing does.
- ~300 pre-existing `ruff` findings across the repo (mostly import ordering). Every file
  touched in this work is clean; the rest was left alone deliberately to keep the diff
  readable.
- `documentation_workflow.py` and the `documents` table are untouched and still work.
  The legacy reader still serves them.
- Open questions are recorded at the foot of both plan documents rather than decided.
