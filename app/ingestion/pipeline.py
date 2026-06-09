from dataclasses import dataclass
from pathlib import Path
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.repo.local import LocalRepoIngester
from app.ingestion.repo.github import GitHubRepoIngester
from app.ingestion.parsers.code_parser import CodeParser, ParsedCodebase
from app.ingestion.parsers.markdown_parser import MarkdownParser

logger = structlog.get_logger(__name__)


@dataclass
class IngestionResult:
    sources_processed: int
    total_files: int
    languages: dict[str, int]
    markdown_files: int
    errors: list[str]


class IngestionPipeline:
    def __init__(self, project, job_id: int, db: AsyncSession) -> None:
        self.project = project
        self.job_id = job_id
        self.db = db
        self.code_parser = CodeParser()
        self.md_parser = MarkdownParser()
        self._last_codebase: ParsedCodebase | None = None

    async def run(self) -> dict:
        result = IngestionResult(
            sources_processed=0,
            total_files=0,
            languages={},
            markdown_files=0,
            errors=[],
        )

        for source in self.project.sources:
            try:
                logger.info("processing_source", source_type=source.source_type, path=source.url_or_path)
                await self._process_source(source, result)
                result.sources_processed += 1
            except Exception as exc:
                logger.error("source_error", source_id=source.id, error=str(exc))
                result.errors.append(f"Source {source.id}: {exc}")

        return {
            "sources_processed": result.sources_processed,
            "total_files": result.total_files,
            "languages": result.languages,
            "markdown_files": result.markdown_files,
            "errors": result.errors,
        }

    async def _process_source(self, source, result: IngestionResult) -> None:
        if source.source_type == "local":
            ingester = LocalRepoIngester()
        elif source.source_type in ("github", "gitlab", "bitbucket"):
            ingester = GitHubRepoIngester()
        else:
            logger.warning("unsupported_source_type", source_type=source.source_type)
            return

        clone_result = await ingester.clone(source.url_or_path, branch=source.branch)
        root_path: Path = clone_result.local_path

        # Parse code
        codebase: ParsedCodebase = self.code_parser.parse_directory(root_path)
        self._last_codebase = codebase
        result.total_files += codebase.total_files
        for lang, count in codebase.languages.items():
            result.languages[lang] = result.languages.get(lang, 0) + count

        # Parse markdown docs
        md_docs = self.md_parser.parse_directory(root_path)
        result.markdown_files += len(md_docs)

        logger.info(
            "source_parsed",
            files=codebase.total_files,
            languages=list(codebase.languages.keys()),
            md_files=len(md_docs),
        )
