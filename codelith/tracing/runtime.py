from __future__ import annotations

import contextvars
import logging
from pathlib import Path
from typing import Any

from codelith.config import get_settings
from codelith.tracing import NullSpanTracer, RichTracer, Tracer, TracerConfig

_current_tracer: contextvars.ContextVar[Tracer | None] = contextvars.ContextVar(
    "docany_current_tracer",
    default=None,
)


def create_tracer(
    *,
    job_id: str,
    workflow_type: str,
    run_dir: str | Path,
) -> Tracer:
    settings = get_settings()

    cfg = TracerConfig(
        enabled=settings.TRACING_ENABLED,
        log_steps=settings.TRACING_LOG_STEPS,
        max_output_preview_chars=settings.TRACING_MAX_OUTPUT_PREVIEW_CHARS,
        indent_spaces=settings.TRACING_INDENT_SPACES,
        show_inputs=settings.TRACING_SHOW_INPUTS,
        show_outputs=settings.TRACING_SHOW_OUTPUTS,
        max_preview_chars=settings.TRACING_MAX_PREVIEW_CHARS,
    )

    span_tracer = RichTracer() if cfg.log_steps else NullSpanTracer()

    tracer = Tracer(
        config=cfg,
        span_tracer=span_tracer,
        meta={
            "project": "codelith",
            "job_id": job_id,
            "workflow_type": workflow_type,
            "run_dir": str(run_dir),
        },
        logger_=logging.getLogger("docany.tracing"),
    )
    # Write each step's JSON the moment it completes so the steps/ folder
    # fills up incrementally during the run, not only after it finishes.
    if settings.TRACING_SAVE_JSON:
        steps_dir = Path(run_dir) / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        tracer._live_steps_dir = steps_dir
    return tracer


def set_tracer(tracer: Tracer | None) -> Any:
    return _current_tracer.set(tracer)


def reset_tracer(token: Any) -> None:
    _current_tracer.reset(token)


def get_tracer() -> Tracer:
    tracer = _current_tracer.get()
    if tracer is not None:
        return tracer
    # Safe no-op fallback — prevents crashes when called outside a workflow job
    return Tracer(
        config=TracerConfig(enabled=False, log_steps=False),
        span_tracer=NullSpanTracer(),
    )


def save_trace_artifacts(tracer: Tracer, run_dir: str | Path) -> dict[str, str]:
    settings = get_settings()
    trace_dir = Path(run_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {}

    if settings.TRACING_SAVE_JSON:
        json_path = trace_dir / "trace.json"
        json_path.write_text(tracer.results.model_dump_json(indent=2), encoding="utf-8")
        paths["trace_json"] = str(json_path)

        # Per-step files: 001_agent_coordinator_agent.json, 002_llm_planner_agent.json, …
        steps_dir = trace_dir / "steps"
        steps_dir.mkdir(exist_ok=True)
        for step in tracer.results.steps:
            agent_slug = (step.agent_id or "unknown").replace(" ", "_").replace("/", "-")
            filename = f"{step.step_id:03d}_{step.kind}_{agent_slug}.json"
            (steps_dir / filename).write_text(step.model_dump_json(indent=2), encoding="utf-8")
        paths["steps_dir"] = str(steps_dir)

    if settings.TRACING_SAVE_MARKDOWN:
        md_path = trace_dir / "trace.md"
        md_path.write_text(tracer.render(format="markdown"), encoding="utf-8")
        paths["trace_markdown"] = str(md_path)

    return paths


def short_error(exc: BaseException, max_chars: int = 500) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:max_chars - 3] + "..." if len(text) > max_chars else text
