# Codelith — Progress

Execution tracker for [CODELITH_PLAN.md](CODELITH_PLAN.md). Update the status column as
work lands; keep notes on anything that contradicted the plan.

Legend: ⬜ not started · 🟨 in progress · ✅ done · ⛔ blocked · ⏭️ deferred

## Summary

| Phase | Scope | Status |
|---|---|---|
| C0 | Housekeeping | ✅ |
| C1 | The rename | ✅ |
| C2 | A feature is a thing the KB unlocks | ✅ |
| C3 | The project becomes the hub | ✅ |
| C4 | The rail | ✅ |
| C5 | The landing page | ✅ |
| C6 | Verification | ✅ |

**787 unit tests + 25 chat integration tests passing.** UI typechecks and builds.
Verified against the running stack, not fixtures.

---

## Phase C0 — Housekeeping ✅

| # | Task | Status | Notes |
|---|---|---|---|
| C0.1 | Uncommitted `questions.py` change | ✅ | Committed. The artefact profile is unconditional now — gated on entity kinds it fired 1 run in 2, on the `entities` intent 2 in 3, and every miss produced the container-image answer |
| C0.2 | Clean tree before the rename | ✅ | |

## Phase C1 — The rename ✅

| # | Task | Status | Notes |
|---|---|---|---|
| C1.1 | `pyproject.toml`, CLI entry point | ✅ | |
| C1.2 | Sweep the old name | ✅ | Wordmark keeps its accent dot: `code·lith` |
| C1.3 | Rewrite `CLAUDE.md` | ✅ | Now states analysis is the product, and the rule that keeps it true |
| C1.4 | Rename the GitHub repository | ⬜ | **Yours to do** — the local remote still points at `document-anything` |
| C1.5 | Docker compose project name | ⏭️ | Renaming recreates containers and orphans the volumes. Cosmetic, and the cost is a re-analysis |
| C1.6 | Nothing stored carries the old name | ✅ | DB name and S3 bucket keep `documentanything` — private identifiers, rename costs a data reset for no visible benefit |

## Phase C2 — A feature is a thing the KB unlocks ✅

| # | Task | Status | Notes |
|---|---|---|---|
| C2.1 | `app/features/registry.py` | ✅ | `Feature` + `FeatureState` |
| C2.2 | Requirements in KB vocabulary | ✅ | Shown to the reader — the honest answer to "why is this locked" |
| C2.3 | One availability check, replacing four | ✅ | Found a live drift — see the note below |
| C2.4 | `GET /projects/{id}/features` | ✅ | |
| C2.5 | Planned features are first-class | ✅ | Supported, and **none are listed** — see the note |
| C2.6 | Tests | ✅ | 17, each guard verified by disabling it |

## Phase C3–C5 — The surfaces ✅

| # | Task | Status | Notes |
|---|---|---|---|
| C3.1–C3.5 | Project page as the hub | ✅ | Feature grid full-width under the header; documentation coverage moved inside its card |
| C4.1–C4.3 | The rail | ✅ | "Workspace" and "Ask the code"; Projects reads as Codebases |
| C5.1–C5.6 | Landing page | ✅ | Hero is read-once-use-many; new services section; stages 03/04 are Unlock and Use |

## Phase C6 — Verification ✅

| # | Task | Status | Notes |
|---|---|---|---|
| C6.1 | Full suite | ✅ | 787 + 25 |
| C6.2 | UI typecheck and build | ✅ | |
| C6.3 | End-to-end against the running stack | ✅ | Title `Codelith`; both features available on an analysed project; a real question answered in 17s with 7 citations kept, 0 stripped |
| C6.4 | A project with no KB | ✅ | Created one live: both features locked, reason "Analyse this repository to unlock it" |
| C6.5 | Guards verified by disabling them | ✅ | |

---

## Notes and contradictions

**The plan said the engine was already right, and it was — but one thing had drifted.**
Four call sites each decided independently whether a knowledge base could serve a
request. Three wrote `(READY, STALE, DEGRADED)` by hand; `knowledge_service.py` used
`KBStatus.is_usable`, which excludes `STALE`. The same project could offer a feature on
one screen and refuse it on another, and nothing failed loudly enough to notice. This
is the exact rot C2.3 was written to prevent, already present before the abstraction
existed.

`can_serve_features` and `is_usable` are now deliberately different, and a test pins
them apart — if they ever agree, one is redundant and somebody will delete the wrong
one.

**No planned features are listed.** The plan allowed for dimmed "coming soon" cards and
the registry supports them (`built=False`, rendered as `planned`). None are declared:
the existing pipeline stays as it is, diagrams remain part of documentation rather than
a separate feature, and a card on a roadmap is a promise made inside the product.
Adding one later is a single registry entry.

**`dev.sh --reload` does not work on this machine, and fails silently.** WatchFiles
detects the change, prints `Reloading...`, and the replacement worker never starts — so
the previous one keeps serving. Each attempt leaves an orphaned process still bound to
the port: four servers were listening on 8000 simultaneously, which Windows permits via
`SO_REUSEADDR`. The symptom is that code changes appear to do nothing and restarting
does not help, because a stale listener answers first.

Cost about twenty minutes to diagnose, and the false conclusions along the way were all
plausible — stale bytecode, a shadowing install, a Docker container on the same port.
The decisive test was an import-time `print` that never appeared in the log.

Worth fixing in `dev.sh`: either drop `--reload`, or kill existing listeners on start.
Left alone for now because it is the user's script.

---

## Open

| Item | Why |
|---|---|
| Rename the GitHub repository | Outward-facing; redirects are automatic but it is the user's account |
| `dev.sh` reload | See above. A one-line change, but it is their dev script |
| Database and bucket names | Still `documentanything`. Private identifiers; renaming costs a data reset |
