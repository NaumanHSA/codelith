import os
from pathlib import Path
from app.ingestion.repo.base import BaseRepoIngester, CloneResult


class LocalRepoIngester(BaseRepoIngester):
    async def clone(self, url_or_path: str, branch: str | None = None) -> CloneResult:
        path = Path(url_or_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Local path does not exist: {path}")

        file_count = sum(1 for _ in path.rglob("*") if _.is_file())

        commit_sha = None
        try:
            import git
            repo = git.Repo(path, search_parent_directories=True)
            commit_sha = repo.head.commit.hexsha
        except Exception:
            pass

        return CloneResult(
            local_path=path,
            repo_url=str(path),
            branch=branch or "local",
            commit_sha=commit_sha,
            file_count=file_count,
        )
