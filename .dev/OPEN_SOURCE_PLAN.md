# Shipping Codelith as an open-source project

The product works. What is missing is everything between "it works on this machine"
and "somebody who has never seen it can run it, read it, and contribute to it".

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done · `[-]` deliberately not doing

**License: Apache-2.0.** Permissive, and unlike MIT it carries an explicit patent
grant, which is what a tool that will be embedded in other people's build pipelines
should have. It also matches the author's other published project, so a contributor
meets the same terms twice.

---

## What the survey found

Some of this plan is smaller than it looks, and one part is already built.

**Already done, do not rebuild.** Embedding width is *measured, never configured*:
`embedding_column(dimensions)` accepts the argument and ignores it because the column
is a blob with no declared width; `knowledge/embedding_guard.py` records the model name
and measured width on each knowledge base and refuses to read one built by a different
model, with a message saying to re-analyse. The settings page already shows the
measured dimensions. **So the work is deletion, not detection**: `VECTOR_DIMENSIONS`
still sits in `config.py`, `.env.example` and `codelith doctor`, where it reads as a
setting the operator must keep in step with their model. It is not one, and a setting
that does nothing is worse than no setting.

**The API does not serve the UI.** There is no `StaticFiles` mount in `main.py`. A
single-container Docker image therefore needs a code change, not just a Dockerfile.

**`docker run` cannot produce a working app on its own**, and no amount of packaging
changes that: analysis needs a model, the model runs on the host, and inside a
container `localhost` is the container. The fix is `host.docker.internal` plus telling
the operator so at the moment they are configuring a model.

**Legacy names are still in the tree.** `docany_*` on all nine Prometheus metrics and
the Grafana dashboard that reads them; `.gitlab-ci.yml` deploying `docany-api` into a
`document-anything` namespace; `doc-gen.yml` describing a "document-anything project
ID"; `PROGRESS.md` titled "document-anything — Work Log". Four in-app links point at
`https://github.com/codelith`, which is not the repository.

**CI is `workflow_dispatch` only**, and its own comment says to restore `push` and
`pull_request` before publishing.

---

## Phase 1 — Identity — **done**

Nothing here changes behaviour. It changes what the project claims to be.

`[x]` **1.1** The four in-app GitHub links and the Docusaurus footer point at
`https://github.com/NaumanHSA/codelith`.

`[x]` **1.2** `docany_*` metrics become `codelith_*`, and `docker/grafana/dashboards/`
is updated with them. Renaming metrics without renaming the dashboard that reads them
produces a dashboard of empty panels, which is worse than the old name.

`[x]` **1.3** `pyproject.toml` metadata: the description still says "AI-Powered
Documentation Generation Platform", which is what this was two rewrites ago. Plus
authors, license, classifiers, `[project.urls]`, `readme`.

`[x]` **1.4** Remove `VECTOR_DIMENSIONS` from `config.py`, `.env.example` and the
`doctor` check, and have `doctor` report the *measured* width instead of comparing it
to a number nobody can act on.

`[x]` **1.5** Retire the dead deployment config. `.gitlab-ci.yml` and `k8s/` target
names that no longer exist and a cluster nobody runs; `PROGRESS.md` is an internal work
log that a visitor should not meet first. Log moves to `.dev/`.

## Phase 2 — What a repository needs — **done**

*Also removed `doc-gen.yml`, found while restoring CI: it posted to a hosted
`DOCANY_API_URL` with secrets nobody holds, against the legacy jobs endpoint, for a
deployment that does not exist. A workflow describing the product as a service somebody
calls over the network is the opposite of what it claims to be.*

`[x]` **2.1** `LICENSE` (Apache-2.0), and the header/notice wherever the project
identifies itself.

`[x]` **2.2** `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1, with a real contact.

`[x]` **2.3** `CONTRIBUTING.md`, and specifically *not* a generic one. This repository
has rules a newcomer will break on their first patch: the base may not import an app,
apps may not import each other (`tests/unit/test_module_isolation.py` fails if they
do), no hardcoded colours outside `theme.css`, no language-specific code outside
`codelith/languages/`, DB access only through repositories. Those belong here.

`[x]` **2.4** `SECURITY.md` and `CHANGELOG.md`.

`[x]` **2.5** `.github/`: bug and feature issue templates, a PR template,
`dependabot.yml`.

`[x]` **2.6** CI restored to `push` and `pull_request`, matrixed on 3.11/3.12/3.13,
running the Python suite and the UI build. A repository other people install from needs
CI that runs without being asked.

`[x]` **2.7** A release workflow: build and publish to PyPI on a tag, via trusted
publishing. Wired but not fired — publishing is the maintainer's call.

## Phase 3 — Docker that actually opens in a browser

`[x]` **3.1** `.dockerignore`. There is none, so the build context currently includes
`node_modules`, `.git`, `repos/`, `.venv` and every cache directory.

`[x]` **3.2** Multi-stage `Dockerfile`: a Node stage builds the studio, a Python stage
installs the package and copies `dist/` in.

`[x]` **3.3** Serve the studio from FastAPI — a SPA fallback mounted *after* the API
router and the published-docs router, so it cannot shadow either. This is the change
that makes one container enough.

`[x]` **3.4** `docker-compose.yml`: one service, a named volume for `~/.codelith` so a
knowledge base survives `docker compose down`, `extra_hosts` for
`host.docker.internal`, and a commented block for the hosted-model path. A `make
docker` target.

`[x]` **3.5** Tell the operator about `host.docker.internal` **where they configure a
model**, not in a README they read once. The settings page knows whether it is running
in a container; a base URL of `localhost` from inside one is a mistake the app can see
coming.

`[x]` **3.6** Build it, run it, sign in through a browser, confirm the studio loads and
the API answers. A Dockerfile that has never been run is a guess.

## Phase 4 — The README and what it shows

`[x]` **4.1** Screenshots of the studio against real data: home, the knowledge graph,
the source viewer, a published site.

`[x]` **4.2** An architecture diagram in the product's own visual language — read once,
serve it: ingest → analyse → knowledge base → the apps and MCP that consume it.

`[x]` **4.3** Rewrite `README.md`: banner, badges that resolve, one paragraph on what
it is, the diagram, what is in the box, quick start, Docker, MCP setup for Claude Code
and Cursor, install options, license, support.

## Phase 5 — Fresh data

Needs a model. LM Studio supplies the fast and embedding tiers; the quality tier runs
on OpenAI.

`[ ]` **5.1** Remove the two existing codebases.

`[ ]` **5.2** Add and analyse: `codelith` itself, `neurosurfer`, `watchtower`.

`[ ]` **5.3** Re-take the screenshots against that data.

`[ ]` **5.4** Confirm the two things that have never run on real data: narrative
provenance, which is empty until an analysis runs with the recording writer, and
drift's architecture diff, which needs two readings of one repository.

---

## Deliberately not doing

`[-]` **Publishing to PyPI.** The workflow is built; firing it is the maintainer's,
with the maintainer's token.

`[-]` **A dark theme.** The tokens are structured for it and no component has been
checked against it. That is its own piece of work, not a line item in a release.

`[-]` **Re-adding a Kubernetes deployment.** The one in the tree is dead. Docker
Compose is the right level for "somebody wants to run this", and a chart nobody
maintains is a promise the project cannot keep.

---

## Risks

- **The Docker image needs the UI toolchain.** Node 20.19+ in the build stage, and the
  studio's build runs `check-markdown` and `check-highlight` — both of which stand up a
  Vite server. If either is flaky in a container, the image build fails, and it should
  fail loudly rather than shipping an unbuilt UI.
- **Analysis in Phase 5 is the long pole** and cannot be shortened: several repositories,
  many model calls each, and Neurosurfer is large.
- **Renaming metrics is a breaking change** for anybody already scraping them. Nobody
  is, because nobody has installed this yet, which is exactly why now is the moment.
