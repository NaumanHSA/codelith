.PHONY: help dev stop build migrate migrate-create seed test lint format typecheck worker

PYTHON := python
ALEMBIC := alembic
DOCKER_COMPOSE := docker compose

help:
	@echo "document-anything — available targets:"
	@echo "  make dev            Start all Docker services + hot-reload API"
	@echo "  make stop           Stop all Docker services"
	@echo "  make build          Build Docker images"
	@echo "  make migrate        Run pending Alembic migrations"
	@echo "  make migrate-create Run: make migrate-create msg='your message'"
	@echo "  make seed           Seed dev database with sample data"
	@echo "  make worker         Start Celery worker locally"
	@echo "  make test           Run full test suite"
	@echo "  make lint           Run ruff linter"
	@echo "  make format         Auto-format with ruff"
	@echo "  make typecheck      Run mypy"

dev:
	$(DOCKER_COMPOSE) up -d postgres redis qdrant neo4j minio prometheus grafana
	@echo "Infrastructure ready. Starting API..."
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

stop:
	$(DOCKER_COMPOSE) down

build:
	$(DOCKER_COMPOSE) build

migrate:
	$(ALEMBIC) upgrade head

migrate-create:
	$(ALEMBIC) revision --autogenerate -m "$(msg)"

seed:
	$(PYTHON) scripts/seed_dev.py

worker:
	celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

test:
	pytest tests/ -v --cov=app --cov-report=term-missing

lint:
	ruff check app/ tests/

format:
	ruff format app/ tests/
	ruff check --fix app/ tests/

typecheck:
	mypy app/
