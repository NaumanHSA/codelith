.PHONY: help dev migrate migrate-create seed test test-unit test-int lint format typecheck \n        docker docker-build docker-logs docker-down

PYTHON     := PYTHONPATH=. python
ALEMBIC    := PYTHONPATH=. alembic

help:
	@echo ""
	@echo "codelith — available targets:"
	@echo ""
	@echo "  Local development (nothing to start but this):"
	@echo "    make dev            Run the API on :8000"
	@echo "    make migrate        Apply DB migrations"
	@echo "    make seed           Create default org + admin user"
	@echo ""
	@echo "  Testing (no services, ~30 seconds):"
	@echo "    make test           Full test suite (unit + integration)"
	@echo "    make test-unit      Unit tests only"
	@echo "    make test-int       Integration tests — a temporary SQLite file"
	@echo ""
	@echo "  Code quality:"
	@echo "    make lint           Run ruff linter"
	@echo "    make format         Auto-format with ruff"
	@echo "    make typecheck      Run mypy"
	@echo ""
	@echo "  Docker (one container: API, studio and database):"
	@echo "    make docker         Build and start it, then open :8000"
	@echo "    make docker-build   Rebuild the image without starting"
	@echo "    make docker-logs    Follow the container's output"
	@echo "    make docker-down    Stop it (the knowledge base survives)"
	@echo ""
	@echo "  The studio is a pnpm project: cd ui && pnpm install && pnpm dev"
	@echo ""

# ── Local dev ─────────────────────────────────────────────────────────────────
# One process. The database is a file under ~/.codelith, created on first use, and
# long work runs on a background thread inside the API — there is no worker to start.

dev:
	./dev.sh

migrate:
	$(ALEMBIC) upgrade head

migrate-create:
	$(ALEMBIC) revision --autogenerate -m "$(msg)"

seed:
	$(PYTHON) scripts/seed_dev.py

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


# ── Docker ────────────────────────────────────────────────────────────────────
# One image, one port. The studio is built into it and served by the API, so there
# is a single address to open and no CORS between them.
#
# The model stays on the host — it has to; inside a container `localhost` is the
# container. Compose maps `host.docker.internal` to the host for exactly that, and
# the studio says so at the field where a model endpoint is typed.

docker:
	docker compose up --build -d
	@echo ""
	@echo "  Codelith is on http://localhost:8000"
	@echo "  Sign in with admin@codelith.dev / admin1234"
	@echo ""

docker-build:
	docker compose build

docker-logs:
	docker compose logs -f

# `down` without -v on purpose: the named volume holds every knowledge base that has
# been built, and rebuilding one is hours of model calls.
docker-down:
	docker compose down
