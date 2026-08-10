"""
Asking a codebase a question.

Streams over a plain `POST` with a chunked body rather than an SSE `GET`. EventSource
cannot set headers, which is why the job-log stream carries its JWT as `?token=` — a
credential in a URL that lands in logs and history. A question is also a body, not a
query string: it has newlines and no length limit worth defending. The studio reads
this with `fetch` and a stream reader, so the token stays in the `Authorization`
header where it belongs.

The wire format is still SSE-shaped (`data: {...}\\n\\n`), because it is a good format
for this and browsers parse it easily — only the transport differs.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from codelith.core.cancellation import JobCancelled
from codelith.core.exceptions import NotFoundError, ValidationError
from codelith.dependencies import CurrentUser, DbSession
from codelith.apps.ask.service import AskService
from codelith.apps.ask.threads import ChatService
from codelith.services.project_service import ProjectService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/projects/{project_id}/chat", tags=["Chat"])

#: The rail's list is not about one project, so it cannot live under one.
threads_router = APIRouter(prefix="/chat", tags=["Chat"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    #: Omit to continue the most recent conversation, or start the first one.
    thread_id: int | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    token_count: int = 0
    evidence: dict = Field(default_factory=dict, validation_alias="evidence_json")
    citations: list = Field(default_factory=list, validation_alias="citations_json")
    stripped: list = Field(default_factory=list, validation_alias="stripped_json")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ThreadOut(BaseModel):
    id: int
    title: str
    messages: list[MessageOut] = Field(default_factory=list)
    #: Everything this conversation costs so far, and the room it has.
    token_count: int = 0
    context_window: int = 0

    model_config = {"from_attributes": True, "populate_by_name": True}


class ThreadSummary(BaseModel):
    """One row in the rail. No messages — a list of forty conversations should not
    carry every word of all of them."""

    id: int
    project_id: int
    project_name: str
    title: str
    message_count: int
    last_message_at: datetime | None = None


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/stream")
async def ask(
    project_id: int, req: AskIn, db: DbSession, user: CurrentUser
) -> StreamingResponse:
    """
    Ask, and stream the answer.

    The user's turn is persisted before the model is called, so a question survives a
    failure mid-answer — losing what somebody typed because generation broke is the
    one thing a chat must not do.
    """
    project = await ProjectService(db).get(project_id, user)
    chat = ChatService(db)

    try:
        thread = await chat.get_or_create_thread(project_id, req.thread_id, user.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    history = await chat.history(thread)
    await chat.add_user_message(thread, req.question)
    await db.commit()

    thread_id = thread.id

    async def events() -> AsyncIterator[str]:
        chunks: list[str] = []
        evidence: dict = {}
        yield _event({"type": "thread", "thread_id": thread_id, "title": thread.title})

        try:
            async for item in AskService(db).stream(project, req.question, history):
                if item["type"] == "token":
                    chunks.append(item["text"])
                elif item["type"] == "evidence":
                    evidence = {k: v for k, v in item.items() if k != "type"}
                elif item["type"] == "done":
                    # The answer is stored *after* citation checking, so what is kept
                    # is what the reader saw — not the model's raw output.
                    await chat.add_answer(
                        thread,
                        item["text"],
                        evidence=evidence,
                        citations=item.get("citations", []),
                        stripped=item.get("stripped", []),
                    )
                    await db.commit()
                yield _event(item)

        except ValidationError as exc:
            yield _event({"type": "error", "message": str(exc)})
        except JobCancelled:
            # The reader pressed stop, or closed the tab. Whatever arrived is kept:
            # a partial answer is worth more than a blank turn.
            if chunks:
                await chat.add_answer(
                    thread, "".join(chunks), evidence=evidence, citations=[], stripped=[]
                )
                await db.commit()
            yield _event({"type": "stopped"})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("chat_stream_failed", project_id=project_id)
            yield _event({"type": "error", "message": f"The answer failed: {exc}"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/thread", response_model=ThreadOut | None)
async def current_thread(
    project_id: int, db: DbSession, user: CurrentUser, thread_id: int | None = None
) -> ThreadOut | None:
    """The conversation to show on load: the one named, or the most recent."""
    await ProjectService(db).get(project_id, user)
    chat = ChatService(db)

    thread = (
        await chat.load(project_id, thread_id) if thread_id else await chat.latest(project_id)
    )
    if thread is None:
        return None

    from codelith.llm.router import select_spec

    return ThreadOut(
        id=thread.id,
        title=thread.title,
        messages=[MessageOut.model_validate(m) for m in thread.messages],
        token_count=await chat.token_total(thread.id),
        context_window=select_spec("write").context_window,
    )


@router.delete("/thread/{thread_id}", status_code=204)
async def clear_thread(
    project_id: int, thread_id: int, db: DbSession, user: CurrentUser
) -> None:
    """Empty a conversation, keeping the thread so the studio's id stays valid."""
    await ProjectService(db).get(project_id, user)
    try:
        await ChatService(db).clear(project_id, thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    project_id: int, thread_id: int, db: DbSession, user: CurrentUser
) -> None:
    """Remove a conversation entirely — the row in the rail as well as its messages."""
    await ProjectService(db).get(project_id, user)
    try:
        await ChatService(db).delete_thread(project_id, thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/threads/{thread_id}/export", response_class=PlainTextResponse)
async def export_thread(
    project_id: int, thread_id: int, db: DbSession, user: CurrentUser
) -> PlainTextResponse:
    """A conversation as Markdown, to keep or to paste somewhere."""
    project = await ProjectService(db).get(project_id, user)
    try:
        thread = await ChatService(db).load(project_id, thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in thread.title)[:50]
    return PlainTextResponse(
        ChatService.to_markdown(thread, project.name),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{slug.strip("-") or "conversation"}.md"'
        },
    )


@threads_router.get("/threads", response_model=list[ThreadSummary])
async def list_threads(
    db: DbSession, user: CurrentUser, limit: int = 40
) -> list[ThreadSummary]:
    """Recent conversations across the org's projects, newest first."""
    rows = await ChatService(db).list_threads(user.org_id or 0, limit=limit)
    return [
        ThreadSummary(
            id=thread.id,
            project_id=thread.project_id,
            project_name=project_name,
            title=thread.title,
            message_count=count,
            last_message_at=thread.last_message_at,
        )
        for thread, count, project_name in rows
    ]
