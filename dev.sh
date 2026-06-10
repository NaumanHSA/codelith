#!/usr/bin/env bash
set -e

CONDA_ENV="${CONDA_ENV:-LLMs}"
API_HOST="${APP_HOST:-0.0.0.0}"
API_PORT="${APP_PORT:-8000}"

# ── Cleanup: kill the Celery worker when this script exits ────────────────────
WORKER_PID=""
cleanup() {
    echo ""
    echo "[dev] Shutting down..."
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        kill "$WORKER_PID"
        wait "$WORKER_PID" 2>/dev/null || true
        echo "[dev] Celery worker stopped."
    fi
}
trap cleanup EXIT INT TERM

# ── Start Celery worker in background ─────────────────────────────────────────
echo "[dev] Starting Celery worker (conda env: $CONDA_ENV)..."
conda run --no-capture-output -n "$CONDA_ENV" \
    celery -A app.workers.celery_app worker \
        --loglevel=info \
        --concurrency=4 \
        -Q ingestion,generation,export &
WORKER_PID=$!
echo "[dev] Celery worker PID: $WORKER_PID"

# Brief pause so worker logs print before uvicorn banner
sleep 1

# ── Start API (foreground) ────────────────────────────────────────────────────
echo "[dev] Starting API on http://$API_HOST:$API_PORT (conda env: $CONDA_ENV)..."
exec conda run --no-capture-output -n "$CONDA_ENV" \
    uvicorn app.main:app \
        --host "$API_HOST" \
        --port "$API_PORT" \
        --reload
