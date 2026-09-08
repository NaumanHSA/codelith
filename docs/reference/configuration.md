# Configuration

Every setting is `pydantic-settings` in `codelith/config.py`, read from the environment
or a `.env` file. There are no hardcoded values anywhere else.

`.env` is optional: every setting has a working default, and
[`.env.example`](https://github.com/NaumanHSA/codelith/blob/main/.env.example) documents
all of them in the same order as below.

!!! note "The settings page wins"
    Models configured in the studio under **Settings → Models** override what `.env`
    says. An install that has never opened that page behaves exactly as its `.env`
    describes.

## Application

| Setting | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `development` \| `staging` \| `production` |
| `APP_SECRET_KEY` | — | Change it |
| `APP_DEBUG` | `true` | |
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `8000` | |
| `SQLALCHEMY_ECHO` | `false` | Raw SQL in the log |

## Storage

| Setting | Default | Notes |
|---|---|---|
| `CODELITH_HOME` | `~/.codelith` | Moves the database and storage together |
| `DATABASE_URL` | under `CODELITH_HOME` | Override individually |
| `STORAGE_DIR` | under `CODELITH_HOME` | Documents and exports |
| `REPO_SCRATCH_DIR` | `./repos` | Clones live here while a job reads them |
| `JOB_SANDBOX_BASE_DIR` | `./runs` | Per-job traces and artefacts |

## Models

Four settings per tier, three tiers. See [Models](../getting-started/models.md).

```bash
MODEL_QUALITY_PROVIDER=local          # local | openai
MODEL_QUALITY=qwen/qwen3.5-9b
MODEL_QUALITY_BASE_URL=http://localhost:1234/v1
MODEL_QUALITY_CONTEXT_WINDOW=21000
```

Plus `OPENAI_API_KEY`, sent only by the `openai` provider, and the shared
`LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_STREAMING`, `EMBEDDING_BATCH_SIZE`.

There is **no** embedding-width setting, on purpose.

## Analysis

What one reading costs, and where it stops.

| Setting | Default | Notes |
|---|---|---|
| `ANALYSIS_MAX_SUMMARISED_MODULES` | `40` | **The one worth knowing.** Beyond it, the largest modules are summarised and the rest get no prose |
| `ANALYSIS_SUMMARY_CONCURRENCY` | `6` | Summaries in flight at once |
| `ANALYSIS_MAX_NARRATIVES` | `12` | Cross-cutting topics per reading |
| `ANALYSIS_MODULE_CONTEXT_CHARS` | `6000` | Source given to the summariser, per module |

## Composition and the site

| Setting | Default |
|---|---|
| `COMPOSITION_SECTION_CONCURRENCY` | `4` |
| `COMPOSITION_SECTION_TOKEN_BUDGET` | `6000` |
| `SITE_MAX_PAGES` | `30` |
| `SITE_MAX_PAGES_PER_JOB` | `8` |
| `SITE_MAX_SECTIONS` | `8` |

## Diagrams

Off by default. Both renderers are vendored by the root `package.json`, so a job never
needs the network.

| Setting | Default |
|---|---|
| `DIAGRAMS_ENABLED` | `false` |
| `DIAGRAM_RENDER_PNG` / `DIAGRAM_RENDER_SVG` | `true` |
| `MERMAID_CLI_PATH` / `D2_NODE_PATH` | empty — found on `PATH` |

## Tracing and artefacts

`TRACING_*` controls the per-job trace under `./runs/{job_id}/`; `ARTIFACTS_*` controls
whether each stage's inputs and outputs are saved beside it. Both are on by default and
are the first place to look when an answer seems wrong.

## Observability

`OTEL_ENABLED` is **off by default** — it is the one setting that would open a
connection to something you did not start. The app serves `/metrics` in Prometheus
format regardless; point your own scraper at it if you want one.

## Auth

`JWT_*` for tokens. `GOOGLE_*` and `GITHUB_*` for OAuth, both optional and empty by
default.
