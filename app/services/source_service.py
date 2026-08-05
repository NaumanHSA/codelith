"""
Validating a source before anything is created.

The old flow created the project first and attached the source afterwards, so a typo'd
GitHub URL still left an empty project behind and the user only found out when
analysis failed. Here the source is fetched and inspected *first*; the project is only
created once we know there is something to document.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from app.ingestion.parsers.code_parser import CodeParser
from app.ingestion.repo.bitbucket import BitbucketRepoIngester
from app.ingestion.repo.github import GitHubRepoIngester
from app.ingestion.repo.gitlab import GitLabRepoIngester
from app.ingestion.repo.local import LocalRepoIngester
from app.languages import registry

logger = structlog.get_logger(__name__)

_INGESTERS = {
    "local": LocalRepoIngester,
    "github": GitHubRepoIngester,
    "gitlab": GitLabRepoIngester,
    "bitbucket": BitbucketRepoIngester,
}


@dataclass(slots=True)
class SourceProbe:
    """What we learned by actually fetching the source."""

    ok: bool
    source_type: str
    url_or_path: str
    resolved_path: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    file_count: int = 0
    analysable_files: int = 0
    languages: dict[str, int] | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "source_type": self.source_type,
            "url_or_path": self.url_or_path,
            "resolved_path": self.resolved_path,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "file_count": self.file_count,
            "analysable_files": self.analysable_files,
            "languages": self.languages or {},
            "error": self.error,
        }


class SourceService:
    """Fetches and inspects a source without touching the database."""

    async def probe(
        self, source_type: str, url_or_path: str, branch: str | None = None
    ) -> SourceProbe:
        ingester_cls = _INGESTERS.get(source_type)
        if ingester_cls is None:
            return SourceProbe(
                ok=False,
                source_type=source_type,
                url_or_path=url_or_path,
                error=f"Unsupported source type '{source_type}'",
            )

        try:
            result = await ingester_cls().clone(url_or_path, branch=branch)
        except Exception as exc:
            return SourceProbe(
                ok=False,
                source_type=source_type,
                url_or_path=url_or_path,
                error=self._humanise(exc, source_type, url_or_path),
            )

        root = Path(result.local_path)
        codebase = CodeParser().parse_directory(root)
        analysable = codebase.total_files

        if analysable == 0:
            # Fetching succeeded but there is nothing we can document — better to say
            # so now than to let analysis produce an empty knowledge base.
            return SourceProbe(
                ok=False,
                source_type=source_type,
                url_or_path=url_or_path,
                resolved_path=str(root),
                branch=result.branch,
                commit_sha=result.commit_sha,
                file_count=result.file_count,
                error=(
                    "Fetched successfully, but no files in a supported language were "
                    f"found. Supported today: {', '.join(registry.languages())}."
                ),
            )

        return SourceProbe(
            ok=True,
            source_type=source_type,
            url_or_path=url_or_path,
            resolved_path=str(root),
            branch=result.branch,
            commit_sha=result.commit_sha,
            file_count=result.file_count,
            analysable_files=analysable,
            languages=dict(codebase.languages),
        )

    @staticmethod
    def _humanise(exc: Exception, source_type: str, url_or_path: str) -> str:
        """Turn a clone failure into something a user can act on."""
        text = str(exc).lower()

        if source_type == "local":
            return f"Could not read '{url_or_path}'. Check the path exists and is readable."
        if "authentication" in text or "403" in text or "denied" in text:
            return "Access denied — the repository is private or the credentials are wrong."
        if "not found" in text or "404" in text or "repository does not exist" in text:
            return "Repository not found. Check the URL and that it is public."
        if "could not resolve" in text or "name or service not known" in text:
            return "Could not reach the host. Check the URL and your network."
        if "branch" in text:
            return "That branch does not exist in the repository."
        if "timed out" in text or "timeout" in text:
            return "Timed out fetching the repository. It may be very large, or unreachable."
        return f"Could not fetch the repository: {exc}"


__all__ = ["SourceService", "SourceProbe"]
