.PHONY: help infra infra-stop prod prod-stop build migrate migrate-create seed test test-unit test-integration worker lint format typecheck

PYTHON     := PYTHONPATH=. python
ALEMBIC    := PYTHONPATH=. alembic
INFRA      := docker compose -f docker-compose.infra.yml
PROD       := docker compose -f docker-compose.prod.yml

help:
	@echo ""
	@echo "document-anything — available targets:"
	@echo ""
	@echo "  Local development (API runs on your machine):"
	@echo "    make infra          Start infra services only (postgres, redis, minio, neo4j, ...)"
	@echo "    make infra-stop     Stop infra services"
	@echo "    make migrate        Apply DB migrations"
	@echo "    make seed           Create default org + admin user"
	@echo "    make worker         Start Celery worker (separate terminal)"
	@echo ""
	@echo "  Production (everything in Docker):"
	@echo "    make prod           Start full production stack"
	@echo "    make prod-stop      Stop production stack"
	@echo "    make build          Build Docker images"
	@echo ""
	@echo "  Testing:"
	@echo "    make test           Full test suite (unit + integration)"
	@echo "    make test-unit      Unit tests only (no infra needed)"
	@echo "    make test-int       Integration tests (needs infra running)"
	@echo ""
	@echo "  Code quality:"
	@echo "    make lint           Run ruff linter"
	@echo "    make format         Auto-format with ruff"
	@echo "    make typecheck      Run mypy"
	@echo ""

# ── Local dev ─────────────────────────────────────────────────────────────────

infra:
	$(INFRA) up -d
	@echo ""
	@echo "Infrastructure is up. Now run:"
	@echo "  make migrate   (first time only)"
	@echo "  make seed      (first time only)"
	@echo "  uvicorn app.main:app --reload"

infra-stop:
	$(INFRA) down

migrate:
	$(ALEMBIC) upgrade head

migrate-create:
	$(ALEMBIC) revision --autogenerate -m "$(msg)"

seed:
	$(PYTHON) scripts/seed_dev.py

worker:
	celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

# ── Production ────────────────────────────────────────────────────────────────

prod:
	$(PROD) up -d

prod-stop:
	$(PROD) down

build:
	$(PROD) build

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	pytest tests/ -v --cov=app --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-int:
	pytest tests/integration/ -v

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	ruff check app/ tests/

format:
	ruff format app/ tests/
	ruff check --fix app/ tests/

typecheck:
	mypy app/
