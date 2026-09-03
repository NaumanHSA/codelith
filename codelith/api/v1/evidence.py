"""
The material behind one citation, fetched when somebody asks to see it.

An answer lists what it was built from — `src/faceAttr/faceAttr.js:1-17`, `README.md:
271-283` — and until now that was all a reader got. A path and a line range is a
promise that something is there; it is not the thing itself, and checking it meant
leaving the answer, finding the file, and counting lines.

**Fetched, not stored.** The evidence bundle behind an answer runs to forty items and
several kilobytes each; keeping the text on every message would multiply the size of a
conversation by the size of the code it quoted, for material that is already in the
knowledge base. The title carries a path and a line range, which is enough to go and
get it — so a source opens against what is stored *now*, and a chunk that has since
been re-analysed shows the current text rather than a stale copy.

Only `code` and `prose` resolve here. The other kinds an answer cites — an entity, a
graph traversal, a narrative topic — are not spans of a file, and their titles already
say the whole of what they are.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.constants import KBStatus
from codelith.memory.vector_store import VectorStore
from codelith.models.knowledge import KnowledgeBase
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Evidence"])

#: `path/to/file.py:12-48`, which is the shape `Evidence.title` uses for a span. The
#: range is optional: `read_file` cites a whole file.
_SPAN = re.compile(r"^(?P<path>.+?)(?::(?P<start>\d+)-(?P<end>\d+))?$")


class EvidenceOut(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None
    content: str
    #: True when the stored chunks did not cover the whole range asked for — the file
    #: has been re-analysed and chunked differently since the answer was written.
    partial: bool = False
    language: str | None = None


@router.get("/{project_id}/evidence", response_model=EvidenceOut)
async def read_evidence(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    ref: str = Query(
        min_length=1,
        max_length=400,
        description="A citation title: `path/to/file.py` or `path/to/file.py:12-48`.",
    ),
) -> EvidenceOut:
    """
    The source behind one citation.

    404s when nothing matches rather than returning an empty string: "this file is not
    in the knowledge base" and "this file is empty" are different answers, and only one
    of them means the citation was wrong.
    """
    await ProjectService(db).get(project_id, user)

    match = _SPAN.match(ref.strip())
    if not match:
        raise HTTPException(status_code=422, detail="That is not a citation reference.")
    path = match.group("path").strip()
    start = int(match.group("start")) if match.group("start") else None
    end = int(match.group("end")) if match.group("end") else None

    kb = (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == project_id)
            .order_by(KnowledgeBase.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if kb is None or not KBStatus(kb.status).can_serve_features:
        raise HTTPException(status_code=409, detail="This codebase has not been analysed.")

    chunks = await VectorStore(db).get_by_paths(kb.id, [path], limit_per_path=40)
    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=f"'{path}' is not in this knowledge base. It may have been excluded, "
            "or removed since this answer was written.",
        )

    # Every chunk overlapping the cited range. Chunk boundaries are not line
    # boundaries, so asking for 12-48 can mean two stored chunks or half of one, and
    # showing the overlapping chunks whole is more useful than slicing them to the
    # exact lines — the surrounding context is what makes a snippet readable.
    if start is not None and end is not None:
        wanted = [
            c
            for c in chunks
            if c.start_line is not None
            and c.end_line is not None
            and c.start_line <= end
            and c.end_line >= start
        ]
    else:
        wanted = chunks

    if not wanted:
        # The file is here but not those lines — it was re-chunked, or the citation
        # pointed past the end.
        wanted = chunks[:1]
        partial = True
    else:
        partial = False

    wanted.sort(key=lambda c: c.start_line or 0)
    return EvidenceOut(
        path=path,
        start_line=wanted[0].start_line,
        end_line=wanted[-1].end_line,
        content="\n\n".join(c.content or "" for c in wanted).strip(),
        partial=partial,
        language=getattr(wanted[0], "language", None),
    )
