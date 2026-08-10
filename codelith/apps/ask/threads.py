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

from codelith.core.exceptions import NotFoundError
from codelith.llm.context_manager import count_text_tokens
from codelith.models.chat import ChatMessage, ChatThread

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

    async def list_threads(
        self, org_id: int, limit: int = 40
    ) -> list[tuple[ChatThread, int, str]]:
        """
        Recent conversations across an org's projects, for the rail.

        Flat and cross-project on purpose. A thread list nested under whichever
        project happens to be selected is only reachable once you are already in the
        right place, which is the opposite of what a "recent" list is for. Each row
        carries its project name so the reader can tell two similar questions about
        two repositories apart.

        Empty threads are excluded. A thread exists from the moment somebody presses
        New Chat, and one that was never asked anything has no title and nothing in
        it — listing it would put a row called "New conversation" above the real ones
        every time.
        """
        from codelith.models.project import Project

        counted = (
            select(
                ChatMessage.thread_id.label("thread_id"),
                func.count(ChatMessage.id).label("n"),
            )
            .group_by(ChatMessage.thread_id)
            .subquery()
        )

        rows = (
            await self.db.execute(
                select(ChatThread, counted.c.n, Project.name)
                .join(Project, Project.id == ChatThread.project_id)
                .join(counted, counted.c.thread_id == ChatThread.id)
                .where(Project.org_id == org_id)
                .order_by(
                    ChatThread.last_message_at.desc().nullslast(), ChatThread.id.desc()
                )
                .limit(limit)
            )
        ).all()
        return [(t, int(n or 0), name) for t, n, name in rows]

    async def delete_thread(self, project_id: int, thread_id: int) -> None:
        """
        Remove a conversation entirely.

        Distinct from `clear`, which empties a thread and keeps it. Clearing is for
        the conversation you are in — the id the studio is holding stays valid.
        Deleting is for one in the list you are done with.
        """
        thread = await self._thread(project_id, thread_id)
        await self.db.delete(thread)
        await self.db.commit()
        logger.info("chat_thread_deleted", thread_id=thread_id, project_id=project_id)

    @staticmethod
    def to_markdown(thread: ChatThread, project_name: str) -> str:
        """
        A conversation as a file somebody can keep.

        Citations are written out under each answer rather than left inline, because
        the point of exporting is to read it away from the studio, where a chip is
        not clickable and a list of paths is. Unresolved references are named as
        such — an export that quietly drops them would be a cleaner document and a
        less honest one.
        """
        when = (thread.last_message_at or thread.created_at)
        lines = [
            f"# {thread.title}",
            "",
            f"**Repository:** {project_name}  ",
            f"**Exported:** {datetime.now(UTC):%Y-%m-%d %H:%M} UTC  ",
            f"**Last message:** {when:%Y-%m-%d %H:%M} UTC" if when else "",
            "",
            "---",
            "",
        ]

        for message in thread.messages:
            if message.role == "user":
                lines += [f"## {message.content.strip()}", ""]
                continue

            lines += [message.content.strip(), ""]
            if message.citations_json:
                lines += ["**Sources**", ""]
                lines += [f"- `{c}`" for c in message.citations_json]
                lines += [""]
            if message.stripped_json:
                lines += [
                    "**Unverified references** — named in the answer but not found in "
                    "the retrieved evidence:",
                    "",
                ]
                lines += [f"- `{c}`" for c in message.stripped_json]
                lines += [""]
            lines += ["---", ""]

        return "\n".join(line for line in lines if line is not None).rstrip() + "\n"

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
