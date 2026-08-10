# Codelith — Plan

The product was built documentation-first and named for it. That name now argues with
the roadmap: documentation is **one feature** built on the analysis, Ask the Code is a
second, and there are more worth building. The base is the knowledge base, and
everything else is something you can do once a repository has been read.

This unbundles the product, renames it, and rebuilds the surfaces that still say
otherwise.

**The engine is already right.** `analysis_workflow.py` takes no document type and
never has; `ask_service.py` consumes the KB without documentation being involved at
all. Ask the Code proved the model — a second feature grew on the substrate and needed
nothing from the doc pipeline. So this is a repositioning, not a rewrite, and the plan
should be read with that in mind: most phases are surface work, and exactly one
introduces a new concept.

Decisions taken before writing this:

| Question | Answer |
|---|---|
| Name | **Codelith.** `-lith` is stone — monolith, megalith. A codebase read once as layers. Verified clear on npm, PyPI, GitHub, `.dev` and `.ai` |
| Feature naming | **Umbrella brand, plain features.** The studio says "Documentation" and "Ask the code". Family names (Codelith Docs, Codelith Ask) live on the landing page, in CLI subcommands and in package names. Users should not have to learn a private vocabulary to find a button |
| Where features live | **The project is the hub.** Open a project, see its analysis, launch any unlocked feature from there. The rail stays short as features multiply |
| Ecosystem page, like OpenClaw? | **No.** That model works for ~70 separately-installable repos with their own sites. Four features styled as seventy reads as thin and invites a comparison we lose. The landing page tells the *one analysis, many outputs* story instead |
| Does the rename need a migration? | **No.** No table, column or enum contains the product name |
| Keep `document-anything`? | **As the docs feature's identity, optionally.** It is a good name for that feature and only wrong as the name of the whole |

---

## What already exists

Worth stating precisely, because it determines how much of this is real work.

| Piece | Where | State |
|---|---|---|
| Analysis independent of doc type | `app/workflows/analysis_workflow.py` | **Done** — takes no document type |
| KB usability contract | `app/knowledge/constants.py` | **Done** — `KBStatus.is_usable`, `ready`/`stale`/`degraded` |
| A second feature on the substrate | `app/services/ask_service.py` | **Done** — proves the pattern |
| Per-feature gating | `ask_service.py:404`, `page_builder_service.py:122` | Exists, but each service re-implements the same status check |
| Composition separate from analysis | `app/workflows/composition_workflow.py` | **Done** — never re-reads the repository |
| Project detail page | `ui/.../ProjectDetailPage.tsx` | Exists — currently `Source → Documentation` |
| Landing page | `ui/.../LandingPage.tsx` | Exists — 472 lines, documentation-first throughout |

**Missing, and the substance of this plan:** a name, a definition of what a *feature*
is, a project page that launches them, and a landing page that tells the real story.

---

## Phase C0 — Housekeeping

| # | Task | Notes |
|---|---|---|
| C0.1 | Decide the fate of the uncommitted `app/knowledge/questions.py` change | Makes the artefact profile unconditional. Measured: gated on entity kinds it fired 1 in 2; gated on the `entities` intent, 2 in 3; both failures produced the container-image answer. 770 tests pass with it |
| C0.2 | Clean tree before the rename begins | A rename touching ~40 files should not be mixed with unrelated work |

---

## Phase C1 — The rename

**Why first.** Every later phase writes copy, and writing it twice is waste.

| # | Task | Notes |
|---|---|---|
| C1.1 | `pyproject.toml` — package name, description, CLI entry point | `codelith` becomes the console script |
| C1.2 | Sweep `document-anything` / `document·anything` across `app/`, `ui/`, `README.md`, `Makefile`, `docker-compose.yml` | The wordmark in `Shell.tsx` and `LandingPage.tsx` is the visible one |
| C1.3 | Rewrite `CLAUDE.md` | It opens "Open-source documentation generation platform" — the single most load-bearing sentence for anyone (or any agent) working in this repo |
| C1.4 | Rename the GitHub repository | Redirects are automatic; the git remote should still be updated locally |
| C1.5 | Docker compose project name | Containers are currently `document-anything-postgres-1` |
| C1.6 | Check nothing stored in Postgres/MinIO carries the old name | Expected: nothing. Verify rather than assume |

**Exit:** `rg -i "document.anything"` returns only intentional historical references
(CHANGELOG, this plan), and the full suite passes.

---

## Phase C2 — A feature is a thing the KB unlocks

**Why.** This is the only phase that adds a concept, and it is what makes the rest
cheap. Today three services each re-implement "is this KB usable", and nothing can
answer "what can I do with this project?" — which is exactly what the new project page
needs to render.

A feature declares: an id, a display name, what it needs from the knowledge base, and
whether it is built. The KB's status then decides whether it is available.

| # | Task | Notes |
|---|---|---|
| C2.1 | `app/features/registry.py` — a `Feature` descriptor and the list | id, label, blurb, requirement, `built: bool` |
| C2.2 | Express each requirement in terms already in the KB | Docs: retrieval. Ask: retrieval + graph. Maps: graph. Onboarding: narratives |
| C2.3 | One availability check, replacing three | `ask_service`, `page_builder_service`, `revision_service` all call it |
| C2.4 | `GET /projects/{id}/features` | Returns each feature with `available` / `locked` / `planned` and the reason |
| C2.5 | Planned-but-unbuilt features are first-class | They render as dimmed cards, which is how a visitor learns the pitch without marketing copy |
| C2.6 | Tests: a project with no KB, a stale KB, a ready KB | Each guard verified by disabling it |

**Exit:** adding a feature means one entry in the registry and one page. It never
touches analysis. That property is the whole point of the phase.

---

## Phase C3 — The project becomes the hub

| # | Task | Notes |
|---|---|---|
| C3.1 | Analysis status as the top of the project page | `ready` / `stale` / `degraded` / never-analysed, with file and module counts, and a re-run control |
| C3.2 | Feature grid below it | Available features as cards with live counts (4 documents, 3 conversations); planned ones dimmed |
| C3.3 | Never-analysed state says one thing | "Analyse this repository" — no other action offered. Analysis is the base, and the page should make that unmissable |
| C3.4 | Stale KB is not an error | The commit moved on; features still work, and the card should offer a re-analysis rather than blocking |
| C3.5 | Remove `Source → Documentation` framing | Source is an input to analysis, not a step toward docs |

---

## Phase C4 — The rail

| # | Task | Notes |
|---|---|---|
| C4.1 | Section 1: Dashboard, Projects, Jobs | Documents leaves the top level — it is per-project and reachable from the hub |
| C4.2 | Section 2: Ask the code — New chat and the thread list | Keeps its rail. Conversations are a place you return to, not a feature you launch; this is the deliberate exception to C3 |
| C4.3 | Settings stays last | Renumber the index labels |

---

## Phase C5 — The landing page

**The story is "read once, refract into many."** No competitor's documentation tool
can say it, and it is literally what the two-phase architecture does.

| # | Task | Notes |
|---|---|---|
| C5.1 | Hero: one repository → one analysis → N outputs | The existing terminal panel already shows analysis stages and should stay — it is the proof |
| C5.2 | Kill the documentation-first framing | "Documentation that reads your code first" becomes a claim about understanding, not about documents |
| C5.3 | Services section — one block per feature | Built ones described concretely; planned ones honestly labelled. Reuses the C2 registry so the site and the studio cannot disagree |
| C5.4 | "Analyse once, write as many times as you need" becomes the whole-product diagram | It already exists on the page and is currently about writing |
| C5.5 | One CTA into the studio | |
| C5.6 | Keep the offline claim prominent | It is the strongest differentiator and unaffected by any of this |

---

## Phase C6 — Verification

| # | Task | Notes |
|---|---|---|
| C6.1 | Full suite | Currently 770 unit + 25 chat integration |
| C6.2 | UI typecheck and production build | |
| C6.3 | Walk it end to end: add source → analyse → hub → each feature | Against a real repository, not fixtures |
| C6.4 | A project with no KB, from every entry point | The most likely regression: a feature page reached directly by URL |
| C6.5 | Every new guard verified by disabling it | Standing practice in this repo |

---

## Risks

**The rename is broad but shallow.** ~40 files, no schema, no data. The one genuinely
irreversible step is the GitHub rename, and even that redirects.

**`CLAUDE.md` matters more than it looks.** It is the file that tells an agent what
this repository is. Left stale, every future session starts from a wrong premise.

**Dimmed "planned" cards are a promise.** They set expectations in the product, not
just on a marketing page. Only list features actually intended.

**The feature registry can rot.** If `available` is computed in the registry for the
page but re-derived inside a service, they will drift and the studio will offer
something that then refuses. C2.3 exists to prevent exactly that and should not be
skipped for speed.
