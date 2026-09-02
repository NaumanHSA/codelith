import uuid
from pathlib import Path

import git

from codelith.config import get_settings
from codelith.ingestion.repo.base import BaseRepoIngester, CloneResult


class BitbucketRepoIngester(BaseRepoIngester):
    """Clone a Bitbucket repository via HTTPS. Supports app-password auth via URL."""

    async def clone(self, url_or_path: str, branch: str | None = None) -> CloneResult:
        settings = get_settings()
        scratch = Path(settings.REPO_SCRATCH_DIR)
        scratch.mkdir(parents=True, exist_ok=True)
        dest = scratch / str(uuid.uuid4())

        clone_kwargs: dict = {"to_path": str(dest), "depth": 1}
        if branch:
            clone_kwargs["branch"] = branch

        repo = git.Repo.clone_from(url_or_path, **clone_kwargs)
        file_count = sum(1 for _ in dest.rglob("*") if _.is_file())
        commit_sha = repo.head.commit.hexsha

        return CloneResult(
            local_path=dest,
            repo_url=url_or_path,
            branch=branch or repo.active_branch.name,
            commit_sha=commit_sha,
            file_count=file_count,
        )
