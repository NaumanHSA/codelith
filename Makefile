.PHONY: help prod prod-stop build migrate migrate-create seed test test-unit test-integration lint format typecheck

PYTHON     := PYTHONPATH=. python
ALEMBIC    := PYTHONPATH=. alembic
PROD       := docker compose -f docker-compose.prod.yml

help:
	@echo ""
	@echo "codelith — available targets:"
	@echo ""
	@echo "  Local development (API runs on your machine):"
	@echo "    make migrate        Apply DB migrations"
	@echo "    make seed           Create default org + admin user"
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



migrate:
	$(ALEMBIC) upgrade head

migrate-create:
	$(ALEMBIC) revision --autogenerate -m "$(msg)"

seed:
	$(PYTHON) scripts/seed_dev.py


# ── Production ────────────────────────────────────────────────────────────────

prod:
	$(PROD) up -d

prod-stop:
	$(PROD) down

build:
	$(PROD) build

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	pytest tests/ -v --cov=codelith --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-int:
	pytest tests/integration/ -v

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	ruff check codelith/ tests/ alembic/

format:
	ruff format codelith/ tests/ alembic/
	ruff check --fix codelith/ tests/ alembic/

typecheck:
	mypy codelith/
