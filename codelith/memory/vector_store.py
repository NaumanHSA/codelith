from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.chunk import CodeChunk


def _rank_by_cosine(
    rows: list[CodeChunk], query: list[float], limit: int
) -> list[CodeChunk]:
    """
    Exact nearest neighbours over the rows the filters already narrowed to.

    Deliberately brute force. Measured on 768-dimension vectors: 0.6ms over the 1,692
    chunks of a 257-file repository, 3ms over 50,000, 10ms over 200,000 — faster than
    the round trip to a database that could do it, and exact where HNSW is
    approximate. It also costs no native extension, which is the whole point: a local
    install that needs a compiled SQLite plugin is one that fails on somebody's
    machine.

    The ceiling is memory, not time — 200,000 chunks is roughly 600MB as float32 —
    and a single machine reading a single repository is nowhere near it.
    """
    if not rows:
        return []

    import numpy as np

    q = np.asarray(query, dtype="float32")
    q_norm = float(np.linalg.norm(q))
    if q_norm == 0.0:
        # A zero query has no direction, so every distance is equally meaningless.
        # Returning the first `limit` rows is arbitrary; returning nothing is honest.
        return []

    matrix = np.asarray([r.embedding for r in rows], dtype="float32")
    norms = np.linalg.norm(matrix, axis=1)
    # A zero-vector row would divide by zero. They should not exist, but a single bad
    # embedding must not take out the whole search.
    norms[norms == 0.0] = 1.0
    sims = (matrix @ q) / (norms * q_norm)

    k = min(limit, len(rows))
    # argpartition is O(n) where a full sort is O(n log n); only the top k is ordered.
    top = np.argpartition(-sims, k - 1)[:k]
    return [rows[i] for i in top[np.argsort(-sims[top])]]


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

    async def bulk_add(self, chunks: list[dict]) -> int:
        """
        Insert many chunks in one flush.

        Paired with `create_embeddings`, this replaces the previous
        one-request-and-one-flush-per-chunk ingestion path.
        """
        if not chunks:
            return 0
        self.session.add_all([CodeChunk(**c) for c in chunks])
        await self.session.flush()
        return len(chunks)

    async def delete_by_kb(self, kb_id: int) -> None:
        await self.session.execute(delete(CodeChunk).where(CodeChunk.kb_id == kb_id))

    async def get_by_paths(
        self, kb_id: int, paths: list[str], limit_per_path: int = 6
    ) -> list[CodeChunk]:
        """
        Exact source for known files, in reading order.

        Composition runs as a separate job from analysis, so the cloned repository is
        long gone by then — the chunk text stored here *is* our copy of the source.
        This is what lets a writer be handed real code without re-cloning.
        """
        if not paths:
            return []
        result = await self.session.execute(
            select(CodeChunk)
            .where(CodeChunk.kb_id == kb_id, CodeChunk.source_path.in_(paths))
            .order_by(CodeChunk.source_path, CodeChunk.start_line)
        )
        chunks = list(result.scalars().all())

        # Cap per file so one large module cannot crowd out the others.
        kept: list[CodeChunk] = []
        seen: dict[str, int] = {}
        for chunk in chunks:
            count = seen.get(chunk.source_path, 0)
            if count < limit_per_path:
                kept.append(chunk)
                seen[chunk.source_path] = count + 1
        return kept

    async def search(
        self,
        project_id: int,
        query_embedding: list[float],
        limit: int = 10,
        chunk_type: str | None = None,
        kb_id: int | None = None,
        exclude_paths: list[str] | None = None,
        chunk_types: Iterable[str] | None = None,
    ) -> list[CodeChunk]:
        """Return the most semantically similar chunks using cosine distance (<=>)."""
        stmt = (
            select(CodeChunk)
            .where(CodeChunk.project_id == project_id)
            .where(CodeChunk.embedding.isnot(None))
        )
        if kb_id is not None:
            # Scope to one KB generation so a re-analysis can't mix old and new source.
            stmt = stmt.where(CodeChunk.kb_id == kb_id)
        if exclude_paths:
            # Skip files already supplied verbatim — spend the budget on new material.
            stmt = stmt.where(CodeChunk.source_path.notin_(exclude_paths))
        if chunk_type:
            stmt = stmt.where(CodeChunk.chunk_type == chunk_type)
        if chunk_types is not None:
            # A set rather than one value, because a retrieval policy asks for "any
            # kind of prose" or "code only" — never for a single type. An empty set
            # means nothing is admissible, which must return nothing rather than
            # silently degrade to no filter at all.
            stmt = stmt.where(CodeChunk.chunk_type.in_(list(chunk_types)))

        # Ranking is the one part of this query that is not portable. Postgres orders
        # by `<=>` inside the database; SQLite has no such operator, so the same
        # filtered rows come back and are ranked here. Both return the same chunks —
        # in fact the local path returns them *more* accurately, because HNSW is an
        # approximate index and this is exact.
        if self._ranks_in_database():
            stmt = stmt.order_by(
                CodeChunk.embedding.cosine_distance(query_embedding)
            ).limit(limit)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())

        rows = list((await self.session.execute(stmt)).scalars().all())
        return _rank_by_cosine(rows, query_embedding, limit)

    def _ranks_in_database(self) -> bool:
        """
        Whether the bound database can order by cosine distance itself.

        Asked of the dialect rather than of a setting: a SQLite database cannot do
        this whatever the configuration claims, and a profile flag that disagreed
        with the connection would fail at query time with a confusing error.
        """
        bind = self.session.get_bind()
        return getattr(getattr(bind, "dialect", None), "name", "") == "postgresql"

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
