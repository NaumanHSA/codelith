from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.core.cancellation import JobCancelled
from app.llm.client import chat_completion
from app.llm.context_manager import count_tokens, trim_to_limit
from app.llm.router import select_model
from app.observability.metrics import llm_call_duration, llm_calls_total, record_llm_tokens
from app.tracing.runtime import get_tracer

logger = structlog.get_logger(__name__)


class EmptyCompletion(RuntimeError):
    """The model returned nothing. Retryable — see `_chat_with_retry`."""

    def __init__(self, model: str) -> None:
        super().__init__(f"{model} returned an empty completion")
        self.model = model


class BaseAgent(ABC):
    name: str = "base_agent"

    def __init__(self, db: AsyncSession, job_id: int) -> None:
        self.db = db
        self.job_id = job_id
        self.log = logger.bind(agent=self.name, job_id=job_id)

    @abstractmethod
    async def run(self, state: dict[str, Any]) -> dict[str, Any]: ...

    # ── Tracing ───────────────────────────────────────────────────────────────

    def _tracer(self):
        return get_tracer()

    # ── LLM calls ─────────────────────────────────────────────────────────────

    async def _call_llm(
        self,
        messages: list[dict],
        task_type: str = "write",
        model: str | None = None,
    ) -> str:
        import time
        settings = get_settings()
        messages = trim_to_limit(messages, settings.REACT_CONTEXT_WINDOW_LIMIT)

        selected_model = model or select_model(task_type)
        token_count = count_tokens(messages)
        self.log.debug("llm_call", model=selected_model, task_type=task_type, tokens=token_count)
        record_llm_tokens(selected_model, prompt_tokens=token_count)

        tracer = self._tracer()
        t0 = time.perf_counter()
        with tracer(
            kind="llm",
            agent_id=self.name,
            label=f"llm.{task_type}",
            start_message=f"LLM [{task_type}] ~{token_count} tokens",
            inputs={"task_type": task_type, "tokens": token_count, "messages": messages},
        ) as t:
            try:
                result = await self._chat_with_retry(messages, selected_model)
                llm_calls_total.labels(
                    model=selected_model, task_type=task_type, status="success"
                ).inc()
                t.outputs(response_len=len(result), response=result)
                return result
            except Exception:
                llm_calls_total.labels(
                    model=selected_model, task_type=task_type, status="error"
                ).inc()
                raise
            finally:
                llm_call_duration.labels(model=selected_model, task_type=task_type).observe(
                    time.perf_counter() - t0
                )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        # Retry transport failures, but never a cancellation: JobCancelled is an
        # Exception, so a blanket predicate would retry it three times with backoff —
        # re-issuing the very LLM calls the user asked us to stop.
        retry=retry_if_exception_type(Exception) & retry_if_not_exception_type(JobCancelled),
        reraise=True,
    )
    async def _chat_with_retry(self, messages: list[dict], model: str) -> str:
        result = await chat_completion(messages, model=model)
        if not (result or "").strip():
            # An empty completion is never a valid answer, and it is not an error the
            # transport reports: observed on job 8, where a reasoning model spent its
            # whole token budget thinking under concurrent load and returned nothing,
            # twice, in 96 seconds. Raising makes the existing backoff cover it.
            raise EmptyCompletion(model)
        return result

    async def _call_llm_json(
        self,
        messages: list[dict],
        task_type: str = "plan",
        retries: int = 3,
    ) -> dict | None:
        """Call LLM expecting JSON, retry up to `retries` times with a repair prompt."""
        current_messages = list(messages)
        for attempt in range(retries):
            raw = await self._call_llm(current_messages, task_type)
            try:
                return json.loads(self._extract_json(raw))
            except (json.JSONDecodeError, ValueError):
                if attempt < retries - 1:
                    current_messages = current_messages + [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was not valid JSON. "
                                "Return ONLY the JSON object — no markdown fences, "
                                "no explanation, no prose before or after."
                            ),
                        },
                    ]

        await self._emit_log("warning", "JSON parse failed after retries — using fallback")
        return None

    # ── Logging & step tracking ────────────────────────────────────────────────

    async def _emit_log(self, level: str, message: str, **extra: Any) -> None:
        from app.services.job_service import JobService
        svc = JobService(self.db)
        await svc.write_log(self.job_id, self.name, level, message, extra or None)

    async def _update_step(self, step_name: str, status: str, output: dict | None = None) -> None:
        from app.db.repositories.job_repo import JobStepRepository
        repo = JobStepRepository(self.db)

        # Stamp the timings the UI derives step duration from.
        timing: dict[str, Any] = {}
        if status == "running":
            timing["started_at"] = datetime.now(UTC)
        elif status in ("completed", "failed"):
            timing["completed_at"] = datetime.now(UTC)

        existing = await repo.list(job_id=self.job_id, agent_name=step_name)
        if existing:
            await repo.update(existing[0].id, status=status, output_json=output or {}, **timing)
        else:
            await repo.create(
                job_id=self.job_id,
                agent_name=step_name,
                status=status,
                input_json={},
                output_json=output or {},
                **timing,
            )
        await self.db.commit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Strip markdown fences and prose around a JSON object."""
        raw = raw.strip()
        # Remove ```json ... ``` fences
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        if "```" in raw:
            raw = raw.split("```")[0]
        # Find first { or [ and last } or ]
        match = re.search(r'[{\[]', raw)
        if match:
            start = match.start()
            end = max(raw.rfind("}"), raw.rfind("]")) + 1
            if end > start:
                raw = raw[start:end]
        return raw.strip()
