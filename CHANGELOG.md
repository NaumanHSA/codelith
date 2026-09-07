# Changelog

All notable changes to Codelith are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The codebase page shows what analysis found.** An architecture map drawn from the
  services, relations and layers analysis has always written and nothing had ever read;
  a reader for the cross-cutting narratives, which were previously twelve topic chips
  with the prose dropped; a knowledge graph you expand from the project down through
  roles, modules, files and the symbols in a file; and a module explorer in place of the
  role radar.
- **A source viewer.** The product's claim is that it read your repository, and until
  now nothing in it showed a line of what it read. Files are rebuilt from the stored
  chunks with real line numbers, syntax highlighting, a symbol outline, and
  `?file=…#L12-L30` addressing so a citation can point at lines. Lines no chunk covered
  are drawn as gaps rather than closed.
- **Both directions of the code graph, in the studio.** What a file imports, who imports
  it, what calls it, what reaches it and how far away, whether a test covers it, and
  which written pages describe it — asked automatically about whatever file you are
  reading, and available to agents as the `before_edit` MCP tool.
- **Publishing.** Documentation sites are published to a capability URL, served
  read-only, taken down or re-run at will, with change detection before a republish.
  Published sites carry a source page per cited file, so a citation in the prose resolves
  to the code it came from.
- **Drift compares architecture maps.** Services that appeared, went, were renamed or
  retyped; connections added, cut or reworded.
- **One container that opens in a browser.** `docker compose up` builds the studio,
  serves it from the API on a single port, creates the database and seeds an account.
  The model stays on your machine: compose maps `host.docker.internal`, and the studio
  says so at the field where a model endpoint is typed, with a button that rewrites it.
- **The API serves the studio.** A SPA fallback mounted after the API and published-docs
  routers, so neither is shadowed and an unknown `/api/...` path still answers a JSON
  404 rather than the page shell.

### Changed

- **Docusaurus exports are runnable.** They ship a `package.json`, a config and the
  scaffolding, so `npm install && npm run build` works on a fresh download.
- **`VECTOR_DIMENSIONS` is gone.** The width of an embedding is measured from the model
  you have loaded and recorded on the knowledge base it built, so any embedding model
  works and a changed one is refused with a message rather than producing nonsense.
- **Prometheus metrics renamed** from `docany_*` to `codelith_*`, with the bundled
  Grafana dashboard updated to match.
- **Drift matches services by what is in them, not what they are called.** Service names
  are written by a model, and two readings of an unchanged repository do not agree on
  them — so a diff whose real content was two new files reported nine services appeared
  and eight went. Services are now paired on the modules they contain, which come from
  the code; the same comparison reports two appeared, one went and seven renamed, and
  an edge between two renamed services is no longer a connection cut.

### Fixed

- **Analysis discards its checkout.** It never had: every run left a full copy of the
  repository behind, one per run rather than one per project, and deleting the project
  did not remove it — while the file viewer's own docstring said the checkout was
  discarded. Clones are now removed when the job ends, whether it succeeded, failed or
  was cancelled, and clones left by earlier versions are swept at startup. A `local`
  source is your own folder and is never touched.
- **Cleanup works on Windows.** Git marks its pack files read-only and a read-only file
  cannot be unlinked there, so removing a clone failed on the first pack file and left
  everything in place.
- **The published-site path guard treats a backslash as a separator on every platform.**
  `pathlib` only does so on Windows, so a Windows-style traversal such as
  `\..\secret.txt` was refused on the machine it was written on and accepted as an
  ordinary filename on Linux, which is what the container and CI run. Not exploitable
  (nothing is named that, so the route answered 404) but the guard's stated contract was
  not being met where it matters, and the suite only caught it once it ran on Linux.

### Removed

- Kubernetes manifests and the GitLab CI pipeline, which targeted names the project no
  longer uses and a cluster nobody runs.

---

Codelith has not had a tagged release yet. The first will be `0.1.0`.
