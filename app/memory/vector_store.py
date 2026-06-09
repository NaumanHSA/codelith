from pgvector.sqlalchemy import Vector
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import CodeChunk


class VectorStore:
    """
    Semantic similarity search over code and document chunks using pgvector.
    Vectors live in the code_chunks table — no extra service required.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        project_id: int,
        source_path: str,
        content: str,
        embedding: list[float],
        chunk_type: str = "code",
        language: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        job_id: int | None = None,
    ) -> CodeChunk:
        chunk = CodeChunk(
            project_id=project_id,
            job_id=job_id,
            source_path=source_path,
            language=language,
            chunk_type=chunk_type,
            content=content,
            start_line=start_line,
            end_line=end_line,
            embedding=embedding,
        )
        self.session.add(chunk)
        await self.session.flush()
        return chunk

    async def search(
        self,
        project_id: int,
        query_embedding: list[float],
        limit: int = 10,
        chunk_type: str | None = None,
    ) -> list[CodeChunk]:
        """Return the most semantically similar chunks using cosine distance (<=>)."""
        stmt = (
            select(CodeChunk)
            .where(CodeChunk.project_id == project_id)
            .where(CodeChunk.embedding.isnot(None))
        )
        if chunk_type:
            stmt = stmt.where(CodeChunk.chunk_type == chunk_type)

        # Order by cosine distance (smallest = most similar)
        stmt = stmt.order_by(CodeChunk.embedding.cosine_distance(query_embedding)).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_project(self, project_id: int) -> None:
        await self.session.execute(
            delete(CodeChunk).where(CodeChunk.project_id == project_id)
        )

    async def delete_by_job(self, job_id: int) -> None:
        await self.session.execute(
            delete(CodeChunk).where(CodeChunk.job_id == job_id)
        )

    async def count(self, project_id: int) -> int:
        result = await self.session.execute(
            select(CodeChunk).where(CodeChunk.project_id == project_id)
        )
        return len(result.scalars().all())
