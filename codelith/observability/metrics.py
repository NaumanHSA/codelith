from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# ── Job metrics ───────────────────────────────────────────────────────────────
job_total = Counter(
    "docany_jobs_total",
    "Total documentation jobs by final status",
    ["status"],  # completed | failed | cancelled
)
job_duration = Histogram(
    "docany_job_duration_seconds",
    "End-to-end job duration in seconds",
    buckets=[30, 60, 120, 300, 600, 1200, 1800, 3600],
)

# ── Agent metrics ─────────────────────────────────────────────────────────────
agent_duration = Histogram(
    "docany_agent_duration_seconds",
    "Agent run duration in seconds",
    ["agent"],
    buckets=[1, 5, 15, 30, 60, 120, 300],
)
agent_runs_total = Counter(
    "docany_agent_runs_total",
    "Total agent invocations",
    ["agent", "status"],  # status: success | error
)
agent_errors_total = Counter(
    "docany_agent_errors_total",
    "Agent errors by agent name",
    ["agent"],
)

# ── LLM / token metrics ───────────────────────────────────────────────────────
llm_tokens_total = Counter(
    "docany_llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "direction"],  # direction: prompt | completion
)
llm_calls_total = Counter(
    "docany_llm_calls_total",
    "Total LLM API calls",
    ["model", "task_type", "status"],  # status: success | error
)
llm_call_duration = Histogram(
    "docany_llm_call_duration_seconds",
    "LLM API call duration in seconds",
    ["model", "task_type"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60],
)

# ── Queue metrics ─────────────────────────────────────────────────────────────
celery_queue_depth = Gauge(
    "docany_celery_queue_depth",
    "Celery queue depth",
    ["queue"],
)


@contextmanager
def time_agent(agent_name: str) -> Generator[None, None, None]:
    """Record agent duration, success/failure counter."""
    start = time.perf_counter()
    try:
        yield
        agent_runs_total.labels(agent=agent_name, status="success").inc()
    except Exception:
        agent_runs_total.labels(agent=agent_name, status="error").inc()
        agent_errors_total.labels(agent=agent_name).inc()
        raise
    finally:
        agent_duration.labels(agent=agent_name).observe(time.perf_counter() - start)


@contextmanager
def time_job() -> Generator[None, None, None]:
    """Record job wall-clock duration."""
    start = time.perf_counter()
    try:
        yield
    finally:
        job_duration.observe(time.perf_counter() - start)


def record_llm_tokens(model: str, prompt_tokens: int, completion_tokens: int = 0) -> None:
    if prompt_tokens:
        llm_tokens_total.labels(model=model, direction="prompt").inc(prompt_tokens)
    if completion_tokens:
        llm_tokens_total.labels(model=model, direction="completion").inc(completion_tokens)


def register_metrics_endpoint(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
