#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

API_HOST="${APP_HOST:-0.0.0.0}"
API_PORT="${APP_PORT:-8000}"
export PYTHONPATH="${PYTHONPATH:-.}"

# ── Pick an interpreter ───────────────────────────────────────────────────────
# A local .venv wins when present: the project needs Python >= 3.12 and a conda env
# shared with other work will not generally have this project's dependencies.
# Force conda instead with USE_CONDA=1, and pick the env with CONDA_ENV.
VENV_DIR="${VENV_DIR:-.venv}"
if [ -z "$USE_CONDA" ] && [ -x "$VENV_DIR/bin/python" ]; then
    RUNNER=("$VENV_DIR/bin")
    ENV_LABEL="venv: $VENV_DIR ($("$VENV_DIR/bin/python" -V 2>&1))"
    run() { "${RUNNER[0]}/$1" "${@:2}"; }
else
    CONDA_ENV="${CONDA_ENV:-LLMs}"
    ENV_LABEL="conda env: $CONDA_ENV"
    run() { conda run --no-capture-output -n "$CONDA_ENV" "$@"; }
fi

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
echo "[dev] Starting Celery worker ($ENV_LABEL)..."
run celery -A app.workers.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    -Q ingestion,generation,export &
WORKER_PID=$!
echo "[dev] Celery worker PID: $WORKER_PID"

# Brief pause so worker logs print before uvicorn banner
sleep 1

# ── Start API (foreground) ────────────────────────────────────────────────────
echo "[dev] Starting API on http://$API_HOST:$API_PORT ($ENV_LABEL)..."
# --reload-dir app: without it watchfiles also watches .venv and restarts the API
# every time a package is installed.
run uvicorn app.main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --reload \
    --reload-dir app
