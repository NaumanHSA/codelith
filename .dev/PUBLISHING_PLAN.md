# Publishing — the plan

Export hands you a ZIP. Publishing gives you a **URL**: the site as it stands,
built once, served read-only, shareable with people who do not have the studio,
and revocable the moment you want it gone.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done · `[-]` deliberately not doing

---

## What is already here

Read the code before planning against it. Four things change the shape of this:

- **`SiteService.export_tree()` already produces a neutral `SiteTree`** — sections,
  pages, markdown, provenance — for the live site or any frozen version, from the
  same code path. Publishing does not need its own reader.
- **`formatters/static_site.py` already renders that tree to complete static HTML**
  in the studio's own theme, with no build step, no CDN, no web font. Its docstring
  is explicit: the output works on an air-gapped machine. The default publish path
  therefore needs **no new renderer and no new dependency**.
- **`DocSiteVersion` already freezes a snapshot** under a label, copying pages rather
  than referencing them. That is the unit worth publishing.
- **`EXPORT_FORMATS` is already `markdown, mkdocs, docusaurus, html, docx`**, built in
  memory and streamed. Publishing is the same renderers, written to disk and served.

## What is deliberately not being built

- `[-]` **A second server process.** `mkdocs serve` is a development server with
  livereload; wrapping it means port allocation, supervision, restart-on-crash and
  teardown, and it breaks the claim `make dev` makes — one process, nothing to
  start. This repo already carries the scar: `dev.sh` documents an afternoon lost
  to orphaned Windows listeners holding :8000 open through `SO_REUSEADDR`. Build
  once, serve from the process that is already running.
- `[-]` **Directory renames for the atomic swap.** Windows cannot rename a directory
  while a request has a file open inside it. Builds are immutable directories and a
  database column points at the current one. Swapping is a row update, rollback is
  the same row update pointing back, and nothing on disk ever moves.
- `[-]` **A public tunnel.** Sharing is local. Nothing leaves the box.

---

## The two questions that shape the model

**"What happens if I publish and nothing changed?"**
Every build records a `content_hash`: a canonical digest over the rendered inputs
(site title, nav order, and each page's section, slug, title, order and markdown)
plus the renderer and its version. Publish compares before it builds. Same hash and
a live build already serving means nothing is dispatched and the studio says so,
with `Rebuild anyway` next to it.

**"What happens if it changed — replace, or keep both?"**
The answer falls out of what a publication *is*. A publication targets
**(project, version label or the live site)**. So:

- Republishing the **same target** replaces it. The URL does not change, which is
  the point of having shared it. The previous build stays on disk for rollback.
- Publishing a **different version label** is a different target, so it gets its own
  publication and its own URL, and both stay up.

The studio never guesses. When the live site is already published and its content
has moved on, the dialog offers exactly those two, in the user's words: *"Replace
the current build — the link keeps working"* or *"Freeze this as a version and
publish it alongside"*, the second of which cuts a `DocSiteVersion` first.

## Sharing, and what it honestly is

A published site is a **capability URL**: `/published/{slug}/…` where the slug ends
in 128 bits of randomness. Anyone holding the link can read it; nobody can guess it.
That is what "shareable with others" has to mean for people who do not have accounts
on this machine, and the studio says so in those words rather than implying more.

Two controls make it revocable: **rotate the link** mints a new slug and breaks every
old one instantly, and **take it down** stops serving and deletes the files.

`[ ]` A stricter `private` visibility, requiring a studio session, is Phase 7. It is
not the default because a session cannot ride a plain browser navigation, and a
sharing feature that only opens in one tab is not one.

---

## Phase 1 — The model, the storage layout, and the hash

`[x]` **1.1** `DocSitePublication`: project, site, target (`live` or a version label),
renderer, slug, visibility, status (`building` / `live` / `failed` / `unpublished`),
`current_build_id`, timestamps, created_by.

`[x]` **1.2** `DocSitePublicationBuild`: publication, job, `content_hash`, renderer
version, byte size, page count, file count, commit sha, status, timestamps. Immutable
once written.

`[x]` **1.3** Alembic migration on top of `c3e9a17d5b28`, `render_as_batch` per the
project's convention.

`[x]` **1.4** Storage layout under `STORAGE_DIR`:
`published/{publication_id}/builds/{build_id}/…`. Build directories are never
mutated and never moved; the pointer is `publications.current_build_id`.

`[x]` **1.5** `content_hash`: canonical, order-stable, and covering everything that
can change the output. A test that reordering a nav entry changes it and that
re-reading the same tree does not.

`[x]` **1.6** Repository, and slug minting (`{project-slug}-{16 hex}`).

## Phase 2 — Building, as a job you can watch

`[x]` **2.1** `Renderer` protocol: `name`, `version`, `available()`, `build(tree, out_dir)`
returning `BuildResult(files, bytes, pages)`.

`[x]` **2.2** `BuiltinRenderer` wrapping `StaticSiteFormatter` — extracts its ZIP into
the build directory, so publishing and exporting produce byte-identical HTML and
there is one renderer to keep correct, not two.

`[x]` **2.3** `publish` job type, and a task that records `job_steps` so the studio's
existing `PipelineTree` and SSE log stream light up with no new progress machinery.
Stages: `resolve` → `render` → `write` → `verify` → `activate`.

`[x]` **2.4** `verify`: every internal link resolves, every referenced asset exists,
no external host appears in the built HTML. The last one is not a nicety — it is the
product's central claim, asserted against its own output.

`[x]` **2.5** Cancellation: `JobCancelled` must not be swallowed, and a cancelled
publish must leave `current_build_id` untouched and remove its partial directory.

`[x]` **2.6** Activation is one row update. A failed or cancelled build never becomes
current, so a half-written site is unreachable rather than served.

## Phase 3 — Serving

`[x]` **3.1** `GET /published/{slug}/{path:path}`, mounted on the app rather than under
`/api/v1`: this is a website, not an API.

`[x]` **3.2** Path traversal: resolve against the build root and reject anything that
escapes it, tested with `../`, absolute paths, encoded separators and symlinks.

`[x]` **3.3** Read-only by construction — the router implements `GET` and `HEAD`, and
nothing else exists to call.

`[x]` **3.4** Directory requests serve `index.html`; a missing file is a 404 in the
site's own styling, not a JSON error.

`[x]` **3.5** `ETag` / `If-None-Match` from the build id, which is immutable, so a
reader who reloads gets a 304 and a republish invalidates everything at once.

`[x]` **3.6** Unpublished or building publications 404. There is no window in which a
half-built site answers.

## Phase 4 — The API

`[x]` **4.1** `POST /projects/{id}/site/publish` — `{target, renderer, force}`. Returns
either `{unchanged: true, publication}` without dispatching, or `{job_id, publication}`.

`[x]` **4.2** `GET /projects/{id}/site/publications` — everything published for this
project, with URL, target, status, size, page count, built time and staleness.

`[x]` **4.3** `POST /publications/{id}/rotate` — new slug, old links dead.

`[x]` **4.4** `DELETE /publications/{id}` — stop serving, delete the files, keep the
row so the history of what was shared survives.

`[x]` **4.5** `POST /publications/{id}/rollback` — point at the previous build.

`[x]` **4.6** Schemas, and the studio's API client.

## Phase 5 — The studio

`[ ]` **5.1** A `Published` panel on the documentation site page: each publication with
its link, target, renderer, when it was built, how big, and how many pages.

`[ ]` **5.2** Publish dialog carrying the two questions above — the unchanged case, and
replace-versus-alongside — in the reader's words.

`[ ]` **5.3** Live job progress inside the panel while a build runs.

`[ ]` **5.4** Copy link, open, rebuild, rotate, roll back, take down.

`[ ]` **5.5** The link is labelled for what it is: anyone with it can read the site.

## Phase 6 — Maturity

`[ ]` **6.1** **Staleness.** A published build knows its commit; the project knows its
current one. The panel says *"3 commits behind"* rather than leaving the reader to
work out whether what they shared is still true.

`[ ]` **6.2** **Provenance.** Every published page footer carries the commit, the
knowledge base and the build date, and `/published/{slug}/provenance.json` carries the
manifest, so CI can assert the docs match `HEAD`.

`[ ]` **6.3** **Retention.** Keep the last N builds per publication, delete the rest.
Disk fills otherwise, and nobody notices until it has.

`[ ]` **6.4** **Citations that resolve.** Pages cite `src/foo.py:12-30`. In the studio
those open real code; in a published site they are dead text today. Emit a code view
per cited file, or inline the excerpt. This is the largest quality gap between an
export and a site somebody trusts.

`[ ]` **6.5** **Search.** MkDocs gives it free; the builtin renderer needs a prebuilt
index. A few KB of JSON and no network.

## Phase 7 — Beyond the default renderer

`[ ]` **7.1** `MkDocsRenderer`, shelling out to `mkdocs build --strict`, offered only
when importable, shipped as `codelith[mkdocs]`. Material pulls fonts and icons from a
CDN by default and must be configured offline, asserted by 2.4's external-host check.

`[ ]` **7.2** `private` visibility requiring a session.

`[ ]` **7.3** Publish to a directory, for teams who want the build committed into
`docs/` themselves.

---

## Risks, sized before starting

- **The inline worker is one serial thread.** A large build blocks analysis. The
  builtin renderer is string formatting and should be milliseconds; measure before
  assuming, and revisit if a real renderer lands in Phase 7.
- **Windows file locking.** Addressed by never moving or renaming a build directory.
  Deletion of an old build can still fail while a file is open; deletion is therefore
  best-effort and retried by retention rather than being fatal.
- **Module isolation.** Publishing is documentation-app work. Models live in
  `codelith/models/` with the rest, per the project layout, but every service, task,
  renderer and route lives under `codelith/apps/documentation/`.
  `tests/unit/test_module_isolation.py` must stay green with no new `KNOWN_LEAKS`.
