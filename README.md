# Document Anything

AI-Powered Documentation Generation Platform — automatically generates technical documentation from source code repositories, files, and documents using a multi-agent LangGraph workflow.

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Python 3.12 (async) |
| Database | PostgreSQL + SQLAlchemy 2.0 async + Alembic |
| Cache / Queue broker | Redis |
| Task queue | Celery |
| Agent workflow | LangGraph |
| LLM | `openai` package → LM Studio (offline, OpenAI-compatible) |
| Vector search | pgvector (PostgreSQL extension — no extra service) |
| Graph DB | Neo4j |
| Object storage | MinIO (S3-compatible) |
| Observability | Prometheus + Grafana + OpenTelemetry |
| Containerization | Docker + Docker Compose |

---

## Quick Start

### 1. Prerequisites

- Python 3.12
- Docker + Docker Compose
- [LM Studio](https://lmstudio.ai/) running locally with a model loaded and server started on `http://localhost:1234`

### 2. Clone & configure

```bash
git clone https://github.com/NaumanHSA/document-anything.git
cd document-anything
cp .env.example .env
```

Edit `.env` — the key settings:

```env
LLM_BASE_URL=http://localhost:1234/v1   # LM Studio server
LLM_DEFAULT_MODEL=local-model           # Model name as shown in LM Studio
```

### 3. Install Python dependencies

```bash
pip install -e ".[dev]"
```

Or with uv (recommended):

```bash
uv sync
```

### 4. Start infrastructure

```bash
make dev
```

This starts: PostgreSQL, Redis, Qdrant, Neo4j, MinIO, Prometheus, Grafana — then launches the API on `http://localhost:8000`.

### 5. Run migrations & seed

```bash
make migrate          # creates all DB tables
make seed             # creates admin@docany.local / admin1234
```

### 6. Start Celery worker (second terminal)

```bash
make worker
```

### 7. Explore the API

Open `http://localhost:8000/docs` for the interactive Swagger UI.

---

## Architecture

### Layered Structure

```
API routes (app/api/v1/)
    ↓
Services (app/services/)
    ↓
Agents (app/agents/)   ←→   LangGraph Workflow (app/workflows/)
    ↓
Repositories (app/db/repositories/)
    ↓
PostgreSQL / Qdrant / Neo4j
```

### Agent Workflow (LangGraph StateGraph)

```
CoordinatorAgent   →   PlannerAgent   →   RepoAnalyzerAgent
                                               ↓
                                          WriterAgent
                                               ↓
                                          ReviewerAgent
                                          ↙         ↘
                              [HUMAN REVIEW GATE]   PublisherAgent
                                                         ↓
                                                     Documents saved
```

### Project Layout

```
document-anything/
├── app/
│   ├── main.py                     FastAPI app factory
│   ├── config.py                   All settings (env-driven via pydantic-settings)
│   ├── dependencies.py             FastAPI DI (db session, current_user)
│   ├── api/v1/                     Route handlers (thin layer)
│   │   ├── auth.py                 /auth/register|login|refresh|me
│   │   ├── organizations.py        /organizations CRUD
│   │   ├── projects.py             /projects CRUD + sources
│   │   ├── jobs.py                 /jobs status|logs|approve|cancel
│   │   └── documents.py            /documents list|get|publish|export
│   ├── core/                       Security, logging, exceptions, middleware
│   ├── db/                         SQLAlchemy session + repositories
│   ├── models/                     ORM models (User, Org, Project, Job, Document)
│   ├── schemas/                    Pydantic v2 request/response schemas
│   ├── services/                   Business logic (auth, project, job, document)
│   ├── agents/                     12 specialized agent classes
│   ├── workflows/                  LangGraph StateGraph + state TypedDicts
│   ├── ingestion/                  Repo cloners + file parsers
│   ├── llm/                        LLM client + prompt templates
│   ├── formatters/                 Output format converters
│   ├── storage/                    S3/MinIO client
│   ├── workers/                    Celery app + task definitions
│   └── observability/              OpenTelemetry + Prometheus metrics
├── alembic/                        DB migrations
├── tests/
│   ├── unit/                       Unit tests (no DB required)
│   └── integration/                Integration tests (needs Docker infra)
├── scripts/
│   └── seed_dev.py                 Dev DB seeder
├── docker/
│   └── prometheus.yml              Prometheus scrape config
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── Makefile
└── PROGRESS.md                     Build phase tracker
```

---

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login → JWT tokens |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| GET | `/api/v1/auth/me` | Current user info |
| POST | `/api/v1/projects` | Create project |
| GET | `/api/v1/projects` | List projects |
| POST | `/api/v1/projects/{id}/sources` | Add source (repo/file/URL) |
| POST | `/api/v1/jobs/projects/{id}/jobs` | Trigger documentation generation |
| GET | `/api/v1/jobs/{id}` | Poll job status |
| GET | `/api/v1/jobs/{id}/logs` | Stream agent logs |
| POST | `/api/v1/jobs/{id}/approve` | Human review approval |
| GET | `/api/v1/documents/projects/{id}/documents` | List generated documents |
| POST | `/api/v1/documents/{id}/export` | Export (pdf/docx/mkdocs) |

---

## Supported Inputs

**Repositories:** GitHub, GitLab, Bitbucket, local folders

**Languages:** Python, JavaScript, TypeScript, Go, Rust, Java, C#, Kotlin, Ruby, PHP, C/C++

**Documents:** PDF, DOCX, Markdown, OpenAPI/Swagger, Dockerfiles, Terraform, Kubernetes YAML

---

## Output Formats

- Markdown (Phase 1 ✅)
- PDF (Phase 4)
- DOCX (Phase 4)
- MkDocs site (Phase 4)
- Docusaurus site (Phase 4)

---

## Development

```bash
make lint         # ruff linter
make format       # ruff auto-format
make typecheck    # mypy
make test         # full pytest suite
```

---

## Docker Services

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 (minioadmin / minioadmin) |
| Neo4j Browser | http://localhost:7474 (neo4j / neo4jpassword) |
| Grafana | http://localhost:3000 (admin / admin) |
| Prometheus | http://localhost:9090 |

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio (or any OpenAI-compatible) endpoint |
| `LLM_API_KEY` | `lm-studio` | API key (LM Studio ignores this) |
| `LLM_DEFAULT_MODEL` | `local-model` | Model name as shown in LM Studio |
| `DATABASE_URL` | postgres://... | PostgreSQL async connection string |
| `REDIS_URL` | redis://localhost:6379/0 | Redis connection |
| `S3_ENDPOINT_URL` | http://localhost:9000 | MinIO endpoint |
| `VECTOR_DIMENSIONS` | `1536` | Must match your embedding model's output dimensions |

---

## Build Phases

See [PROGRESS.md](PROGRESS.md) for the detailed phase tracker.
