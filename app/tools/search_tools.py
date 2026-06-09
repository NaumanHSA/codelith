from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import create_embedding
from app.memory.vector_store import VectorStore
from app.models.chunk import CodeChunk


async def semantic_search(
    query: str,
    project_id: int,
    db: AsyncSession,
    limit: int = 8,
    chunk_type: str | None = None,
) -> list[dict]:
    """Embed the query and return the most relevant code chunks."""
    embedding = await create_embedding(query)
    if not embedding:
        return []

    store = VectorStore(db)
    chunks: list[CodeChunk] = await store.search(
        project_id=project_id,
        query_embedding=embedding,
        limit=limit,
        chunk_type=chunk_type,
    )
    return [
        {
            "path": c.source_path,
            "language": c.language,
            "content": c.content,
            "start_line": c.start_line,
            "end_line": c.end_line,
        }
        for c in chunks
    ]


async def keyword_search(
    keyword: str,
    project_id: int,
    db: AsyncSession,
    limit: int = 10,
) -> list[dict]:
    """Full-text fallback: ILIKE search in chunk content."""
    from sqlalchemy import select
    stmt = (
        select(CodeChunk)
        .where(CodeChunk.project_id == project_id)
        .where(CodeChunk.content.ilike(f"%{keyword}%"))
        .limit(limit)
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()
    return [
        {
            "path": c.source_path,
            "language": c.language,
            "content": c.content,
            "start_line": c.start_line,
        }
        for c in chunks
    ]
