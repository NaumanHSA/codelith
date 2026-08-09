"""
Threads, and the messages in them.

Thin on purpose: `AskService` decides what an answer is, this decides where it is
kept. Splitting them means the answer path can be tested without a database and the
persistence can be tested without a model.

Token counts are written with each message rather than derived on read. The context
wheel then answers from a `SUM` over rows, and a long conversation does not
re-tokenise itself every time somebody types a character.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.llm.context_manager import count_text_tokens
from app.models.chat import ChatMessage, ChatThread

logger = structlog.get_logger(__name__)

#: A thread's title comes from its first question. Long enough to be recognisable in
#: a list, short enough not to wrap.
_TITLE_CHARS = 60


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create_thread(
        self, project_id: int, thread_id: int | None, user_id: int | None
    ) -> ChatThread:
        if thread_id is not None:
            thread = await self._thread(project_id, thread_id)
            return thread

        thread = ChatThread(project_id=project_id, created_by=user_id)
        self.db.add(thread)
        await self.db.flush()
        return thread

    async def _thread(self, project_id: int, thread_id: int) -> ChatThread:
        thread = (
            await self.db.execute(
                select(ChatThread).where(
                    ChatThread.id == thread_id, ChatThread.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        if thread is None:
            # Scoped to the project, so a thread id from another project reads as
            # missing rather than as somebody else's conversation.
            raise NotFoundError("Conversation", thread_id)
        return thread

    async def history(self, thread: ChatThread, limit: int = 40) -> list[dict]:
        """Turns oldest first, in the shape `AskService` takes."""
        rows = (
            await self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.thread_id == thread.id)
                .order_by(ChatMessage.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]

    async def add_user_message(self, thread: ChatThread, content: str) -> ChatMessage:
        message = ChatMessage(
            thread_id=thread.id,
            role="user",
            content=content,
            token_count=count_text_tokens(content),
        )
        self.db.add(message)

        # The first question names the thread. A list of "New conversation" rows is
        # unusable, and asking the reader to title it is a chore nobody does.
        if thread.title in ("", "New conversation"):
            thread.title = content.strip().replace("\n", " ")[:_TITLE_CHARS]

        thread.last_message_at = datetime.now(UTC)
        await self.db.flush()
        return message

    async def add_answer(
        self,
        thread: ChatThread,
        content: str,
        *,
        evidence: dict,
        citations: list[str],
        stripped: list[str],
    ) -> ChatMessage:
        message = ChatMessage(
            thread_id=thread.id,
            role="assistant",
            content=content,
            token_count=count_text_tokens(content),
            evidence_json=evidence,
            citations_json=citations,
            stripped_json=stripped,
        )
        self.db.add(message)
        thread.last_message_at = datetime.now(UTC)
        await self.db.flush()
        return message

    async def load(self, project_id: int, thread_id: int) -> ChatThread:
        """One conversation with its messages, for a reload."""
        thread = (
            await self.db.execute(
                select(ChatThread)
                .options(selectinload(ChatThread.messages))
                .where(ChatThread.id == thread_id, ChatThread.project_id == project_id)
            )
        ).scalar_one_or_none()
        if thread is None:
            raise NotFoundError("Conversation", thread_id)
        return thread

    async def latest(self, project_id: int) -> ChatThread | None:
        """The thread to open when none was named."""
        return (
            await self.db.execute(
                select(ChatThread)
                .options(selectinload(ChatThread.messages))
                .where(ChatThread.project_id == project_id)
                .order_by(ChatThread.last_message_at.desc().nullslast(), ChatThread.id.desc())
                .limit(1)
            )
        ).scalars().first()

    async def clear(self, project_id: int, thread_id: int) -> int:
        """
        Empty a thread, keeping the thread itself.

        Deleting the row instead would invalidate whatever the studio is holding and
        force it to reconcile a missing id mid-session. An empty conversation is the
        same thing to a reader and much simpler to hand back.
        """
        thread = await self._thread(project_id, thread_id)
        result = await self.db.execute(
            delete(ChatMessage).where(ChatMessage.thread_id == thread.id)
        )
        thread.title = "New conversation"
        thread.last_message_at = None
        await self.db.commit()
        logger.info("chat_cleared", thread_id=thread.id, messages=result.rowcount or 0)
        return result.rowcount or 0

    async def token_total(self, thread_id: int) -> int:
        """What this conversation currently costs, for the context wheel."""
        return int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(ChatMessage.token_count), 0)).where(
                        ChatMessage.thread_id == thread_id
                    )
                )
            ).scalar()
            or 0
        )


__all__ = ["ChatService"]
