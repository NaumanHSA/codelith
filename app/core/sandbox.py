import shutil
from pathlib import Path

from app.config import get_settings


class JobSandbox:
    """
    Isolated per-job working directory.

    Layout:
        /tmp/jobs/{job_id}/
          scratch/repo/   ← cloned repository
          memory/         ← agent progress checkpoints (JSON)
          outputs/        ← generated markdown before DB save
          trace/          ← trace.json + trace.md
    """

    def __init__(self, job_id: int | str) -> None:
        settings = get_settings()
        self.job_id = str(job_id)
        self.root = Path(settings.JOB_SANDBOX_BASE_DIR) / self.job_id
        self.scratch = self.root / "scratch"
        self.repo = self.scratch / "repo"
        self.memory = self.root / "memory"
        self.outputs = self.root / "outputs"
        self.trace = self.root / "trace"

    def setup(self) -> None:
        for d in (self.scratch, self.repo, self.memory, self.outputs, self.trace):
            d.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def memory_path(self, name: str) -> Path:
        return self.memory / f"{name}.json"

    def output_path(self, name: str) -> Path:
        return self.outputs / f"{name}.md"

    def __repr__(self) -> str:
        return f"JobSandbox(job_id={self.job_id}, root={self.root})"
