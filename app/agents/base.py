from abc import ABC, abstractmethod
from typing import Any
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import chat_completion
from app.llm.router import select_model

logger = structlog.get_logger(__name__)


class BaseAgent(ABC):
    name: str = "base_agent"

    def __init__(self, db: AsyncSession, job_id: int) -> None:
        self.db = db
        self.job_id = job_id
        self.log = logger.bind(agent=self.name, job_id=job_id)

    @abstractmethod
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        ...

    async def _call_llm(
        self,
        messages: list[dict],
        task_type: str = "write",
        model: str | None = None,
    ) -> str:
        selected_model = model or select_model(task_type)
        self.log.debug("llm_call", model=selected_model, task_type=task_type)
        return await chat_completion(messages, model=selected_model)

    async def _emit_log(self, level: str, message: str, **extra: Any) -> None:
        from app.services.job_service import JobService
        svc = JobService(self.db)
        await svc.write_log(self.job_id, self.name, level, message, extra or None)

    async def _update_step(self, step_name: str, status: str, output: dict | None = None) -> None:
        from app.db.repositories.job_repo import JobStepRepository
        repo = JobStepRepository(self.db)
        existing = await repo.list(job_id=self.job_id, agent_name=step_name)
        if existing:
            await repo.update(existing[0].id, status=status, output_json=output or {})
        else:
            await repo.create(
                job_id=self.job_id,
                agent_name=step_name,
                status=status,
                input_json={},
                output_json=output or {},
            )
        await self.db.commit()
