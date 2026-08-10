#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

API_HOST="${APP_HOST:-0.0.0.0}"
API_PORT="${APP_PORT:-8000}"

# Absolute, not ".". `conda run` executes from its own temporary directory, so a
# relative PYTHONPATH resolves somewhere unrelated and `codelith` becomes whatever else
# happens to be importable.
export PYTHONPATH="${PYTHONPATH:-$(pwd)}"

# Reload is off by default on Windows, and the reason is worth writing down.
#
# WatchFiles detects the change and prints "Reloading...", the replacement worker
# never starts, and the *previous* worker keeps serving — while the orphan stays
# bound to the port. Windows permits several listeners on one port via SO_REUSEADDR,
# so they accumulate: four servers were once listening on 8000 at the same time, and
# whichever answered first won.
#
# The symptom is the worst kind: you edit code, nothing changes, and restarting does
# not help either, because a stale listener answers before your new one. It cost an
# afternoon to diagnose. Set RELOAD=1 to opt back in.
RELOAD_ARGS=()
if [ "${RELOAD:-0}" = "1" ]; then
    RELOAD_ARGS=(--reload --reload-dir codelith)
fi

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

# ── Refuse to start on top of a stale server ──────────────────────────────────
# See the note above: an orphaned listener does not stop a new one binding, it just
# answers first. Better to say so than to serve yesterday's code.
if command -v curl >/dev/null 2>&1 && curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$API_PORT/health"; then
    echo "[dev] Something is already serving on port $API_PORT."
    echo "[dev] Stop it first — a second server will bind anyway and you will not"
    echo "[dev] be able to tell which one is answering."
    exit 1
fi

# ── Start Celery worker in background ─────────────────────────────────────────
echo "[dev] Starting Celery worker ($ENV_LABEL)..."
run celery -A codelith.workers.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    -Q ingestion,generation,export &
WORKER_PID=$!
echo "[dev] Celery worker PID: $WORKER_PID"

# Brief pause so worker logs print before uvicorn banner
sleep 1

# ── Start API (foreground) ────────────────────────────────────────────────────
echo "[dev] Starting API on http://$API_HOST:$API_PORT ($ENV_LABEL)..."
run uvicorn codelith.main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    "${RELOAD_ARGS[@]}"
