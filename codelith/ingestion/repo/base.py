from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CloneResult:
    local_path: Path
    repo_url: str
    branch: str
    commit_sha: str | None
    file_count: int


class BaseRepoIngester(ABC):
    @abstractmethod
    async def clone(self, url_or_path: str, branch: str | None = None) -> CloneResult:
        ...
