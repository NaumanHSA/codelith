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
#: range is optional — `read_file` cites a whole file.
_SPAN = re.compile(r"^(?P<path>.+?):(?P<start>\d+)-(?P<end>\d+)$")

#: A trailing `(markdown, unverified)`. Prose evidence carries its type and its
#: standing in the title, because a block gets reordered and quoted back and the
#: label has to travel with it — see `knowledge/retrieval.py`. It is not part of the
#: path, and treating it as one is why every README citation reported itself missing
#: from a knowledge base it was retrieved from.
_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")

#: Lines of context kept either side of a citation when the stored chunk is much wider
#: than the range asked for. Enough to see what the snippet sits inside; not so much
#: that the answer is a file.
_CONTEXT_LINES = 4


def _parse(ref: str) -> tuple[str, int | None, int | None]:
    """`(path, start, end)` from a citation title."""
    cleaned = _SUFFIX.sub("", ref.strip())
    if match := _SPAN.match(cleaned):
        return match.group("path").strip(), int(match.group("start")), int(match.group("end"))
    return cleaned, None, None


def _dedent(text: str) -> str:
    """
    Remove the indentation the excerpt all shares, and none of the rest.

    A span cut from inside a function carries its enclosing indentation on every line
    — measured on a real citation, sixteen characters of it, which is fifteen per cent
    of the panel's width spent on nothing. Removing the *common* prefix reclaims that.

    Not "remove the indentation", which was the tempting reading: relative indentation
    is what says which lines are inside the `if`. Flattening it would make the excerpt
    wrong rather than narrow.

    Done here rather than when chunks are stored, and that is the substantive choice.
    Stored chunks are the source of truth — they are what a model is given as evidence
    and what a writer quotes, and they are addressed by line number. Dedenting them
    would make the knowledge base disagree with the file it was read from, would need
    a full re-analysis to take effect, and could not be undone. Presentation is where
    the narrow panel is, so presentation is where the fix belongs.

    Tabs are counted as characters, not expanded: mixing them with spaces is already a
    problem in the file, and this must not invent an opinion about it.
    """
    lines = text.split("\n")
    prefixes = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    common = min(prefixes, default=0)
    if not common:
        return text
    return "\n".join(line[common:] if line.strip() else line.strip() for line in lines)


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

    path, start, end = _parse(ref)
    if not path:
        raise HTTPException(status_code=422, detail="That is not a citation reference.")

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

    # One chunk, not every overlapping one. Chunking is deliberately overlapping —
    # `livenessLoop.js` stores 14-129, 87-178, 131-210 and 179-232 among others — so
    # a citation of 177-194 touches three of them, and joining those repeated the same
    # code three times and returned ten kilobytes to show eighteen lines.
    #
    # The tightest chunk that contains the citation wins; failing that, the one that
    # overlaps it most. Either way it is a contiguous piece of one file, which is what
    # makes narrowing it below safe.
    if start is not None and end is not None:
        def rank(c) -> tuple:
            lo, hi = c.start_line or 0, c.end_line or 0
            contains = lo <= start and hi >= end
            overlap = max(0, min(hi, end) - max(lo, start))
            return (0 if contains else 1, hi - lo if contains else -overlap)

        overlapping = [
            c
            for c in chunks
            if c.start_line is not None
            and c.end_line is not None
            and c.start_line <= end
            and c.end_line >= start
        ]
        wanted = [min(overlapping, key=rank)] if overlapping else []
    else:
        wanted = chunks

    if not wanted:
        # The file is here but not those lines — it was re-chunked, or the citation
        # pointed past the end.
        wanted = chunks[:1]
        partial = True
    else:
        partial = False

    text = "\n\n".join(c.content or "" for c in wanted).strip()
    first, last = wanted[0].start_line, wanted[-1].end_line

    # Even the tightest chunk can be far wider than the citation, so it is sliced to
    # the cited lines with a few either side. Line numbers are chunk-relative, which
    # only works because `wanted` is a single contiguous chunk.
    if start is not None and end is not None and len(wanted) == 1 and first is not None:
        span = (last or first) - first
        if span > (end - start) + _CONTEXT_LINES * 4:
            lines = text.splitlines()
            lo = max(0, (start - first) - _CONTEXT_LINES)
            hi = min(len(lines), (end - first) + 1 + _CONTEXT_LINES)
            if lo < hi:
                text = "\n".join(lines[lo:hi])
                first, last = first + lo, first + hi - 1

    return EvidenceOut(
        path=path,
        # The narrowed span and text, not the chunk's own — the block above may have
        # sliced both, and reporting the chunk's range beside a shorter excerpt would
        # be a line count the reader could check and find wrong.
        start_line=first,
        end_line=last,
        content=_dedent(text),
        partial=partial,
        language=getattr(wanted[0], "language", None),
    )
