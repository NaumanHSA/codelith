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
- **Drift compares architecture maps.** Services that appeared, went or were retyped;
  connections added, cut or reworded.

### Changed

- **Docusaurus exports are runnable.** They ship a `package.json`, a config and the
  scaffolding, so `npm install && npm run build` works on a fresh download.
- **`VECTOR_DIMENSIONS` is gone.** The width of an embedding is measured from the model
  you have loaded and recorded on the knowledge base it built, so any embedding model
  works and a changed one is refused with a message rather than producing nonsense.
- **Prometheus metrics renamed** from `docany_*` to `codelith_*`, with the bundled
  Grafana dashboard updated to match.

### Removed

- Kubernetes manifests and the GitLab CI pipeline, which targeted names the project no
  longer uses and a cluster nobody runs.

---

Codelith has not had a tagged release yet. The first will be `0.1.0`.
