"""
Step artifacts — what each agent actually produced.

The tracer already records *that* a stage ran and a handful of counters
(`services=8`, `sections=7`). What it does not record is the payload itself: the
architecture map, the section plan, the prose of a narrative, or the exact context a
section was written from. Those are the things you need in order to judge whether a
stage did a good job, and until now they existed only in workflow state and were
thrown away when the job ended.

Everything lands in `./runs/{job_id}/artifacts/`, numbered in execution order:

    runs/42/artifacts/
      01_repo_analyzer.ingestion.json
      02_structured_extractor.modules.json
      05_architecture_synthesizer.architecture_map.json
      06_narrative_writer.overview.md
      ...

Design notes:

- A **no-op when nothing is bound.** The writer is held in a contextvar set by the
  Celery task, exactly like the tracer. Unit tests and API-process code paths call
  the same helpers and touch no filesystem.
- **Never fatal.** A failed write logs a warning; it must not take down a job that
  is otherwise fine. Only filesystem and serialisation errors are caught, so a
  `JobCancelled` travelling through can never be swallowed here.
- **Bounded.** Each file is capped at `ARTIFACTS_MAX_CHARS`; a section context is a
  few kB but a module inventory on a large repo is not.
"""

from __future__ import annotations

import contextvars
import dataclasses
import enum
import json
import re
import threading
from pathlib import Path
from typing import Any

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _fallback(obj: Any) -> Any:
    """
    JSON encoder of last resort.

    Agents hand us dataclasses, enums, ORM rows and sets. None of that is worth a
    crash — an artifact is a debugging aid, so anything unrecognised degrades to its
    string form rather than raising.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (set, frozenset, tuple)):
        return list(obj)
    if hasattr(obj, "model_dump"):  # pydantic v2
        return obj.model_dump()
    return str(obj)


class ArtifactWriter:
    """Writes numbered artifact files into one job's run directory."""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self._seq = 0
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def write_json(self, name: str, data: Any) -> Path | None:
        return self._write(name, self._encode(data), "json")

    def write_text(self, name: str, text: str, ext: str = "md") -> Path | None:
        return self._write(name, text or "", ext)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _write(self, name: str, body: str, ext: str) -> Path | None:
        settings = get_settings()
        limit = settings.ARTIFACTS_MAX_CHARS
        if limit and len(body) > limit:
            if ext == "json":
                # Cutting JSON at a character count leaves a file that no longer parses
                # — `json.load()` fails mid-string, which is exactly when you most want
                # to read it. Replace it with a valid envelope instead.
                body = json.dumps(
                    {
                        "_truncated": True,
                        "_original_chars": len(body),
                        "_limit": limit,
                        "_note": "raise ARTIFACTS_MAX_CHARS to capture this payload whole",
                        "preview": body[: max(0, limit - 400)],
                    },
                    indent=2,
                )
            else:
                body = body[:limit] + f"\n\n… truncated at ARTIFACTS_MAX_CHARS={limit}\n"

        with self._lock:
            self._seq += 1
            seq = self._seq

        safe = _SAFE_NAME.sub("-", name).strip("-") or "artifact"
        path = self.run_dir / f"{seq:02d}_{safe}.{ext}"
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            logger.warning("artifact_write_failed", artifact=name, error=str(exc))
            return None
        return path

    @staticmethod
    def _encode(data: Any) -> str:
        try:
            return json.dumps(data, indent=2, ensure_ascii=False, default=_fallback)
        except (TypeError, ValueError) as exc:
            logger.warning("artifact_encode_failed", error=str(exc))
            return json.dumps({"_encode_error": str(exc), "repr": repr(data)[:2000]}, indent=2)


_current_writer: contextvars.ContextVar[ArtifactWriter | None] = contextvars.ContextVar(
    "docany_artifact_writer",
    default=None,
)


def create_artifact_writer(run_dir: str | Path) -> ArtifactWriter | None:
    """Build a writer for this job, or None when artifacts are switched off."""
    if not get_settings().ARTIFACTS_ENABLED:
        return None
    return ArtifactWriter(run_dir)


def set_artifact_writer(writer: ArtifactWriter | None) -> Any:
    return _current_writer.set(writer)


def reset_artifact_writer(token: Any) -> None:
    _current_writer.reset(token)


def get_artifact_writer() -> ArtifactWriter | None:
    return _current_writer.get()


# ── Helpers agents call ───────────────────────────────────────────────────────


def save_artifact(name: str, data: Any) -> None:
    """Record an agent's output payload. No-op when disabled or unbound."""
    writer = _current_writer.get()
    if writer is not None:
        writer.write_json(name, data)


def save_text_artifact(name: str, text: str, ext: str = "md") -> None:
    """Record prose (a narrative, a written section) as its own readable file."""
    writer = _current_writer.get()
    if writer is not None:
        writer.write_text(name, text, ext)


def save_input_artifact(name: str, data: Any) -> None:
    """
    Record what went *into* a stage — prompts, retrieved context, inventories.

    Gated separately because these are the large files: a repository's module
    inventory or every section's retrieved context dwarfs the outputs they produce.
    """
    if not get_settings().ARTIFACTS_INCLUDE_INPUTS:
        return
    save_artifact(name, data)


def save_input_text_artifact(name: str, text: str, ext: str = "md") -> None:
    """Prose-shaped counterpart to `save_input_artifact` (a rendered context bundle)."""
    if not get_settings().ARTIFACTS_INCLUDE_INPUTS:
        return
    save_text_artifact(name, text, ext)


__all__ = [
    "ArtifactWriter",
    "create_artifact_writer",
    "get_artifact_writer",
    "reset_artifact_writer",
    "save_artifact",
    "save_input_artifact",
    "save_input_text_artifact",
    "save_text_artifact",
    "set_artifact_writer",
]
