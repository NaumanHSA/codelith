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

#: The provisional title, taken from the first question so the sidebar is never
#: showing a blank row while an answer streams. Replaced once there is an answer to
#: name the conversation by.
_TITLE_CHARS = 60

#: How much of each side of the first exchange the naming call sees. A title needs
#: the subject, not the whole answer.
_TITLE_CONTEXT_CHARS = 700


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

        # Now there is something to name the conversation after. The provisional title
        # is the first message verbatim, and most conversations open with a greeting —
        # a sidebar of rows reading "Hi there" is a sidebar nobody can navigate.
        if await self._needs_naming(thread):
            await self._name(thread, content)

        await self.db.flush()
        return message

    async def _first_question(self, thread: ChatThread) -> str:
        """
        The opening question, by query rather than through `thread.messages`.

        The thread on this path comes from `get_or_create_thread`, which does not
        eager-load its messages — touching the relationship here would be a lazy load
        on an async session, which raises rather than loading.
        """
        row = (
            await self.db.execute(
                select(ChatMessage.content)
                .where(ChatMessage.thread_id == thread.id, ChatMessage.role == "user")
                .order_by(ChatMessage.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        return (row or "").strip()

    async def _needs_naming(self, thread: ChatThread) -> bool:
        """
        Whether this thread has yet to be named properly.

        True while the title is still the placeholder or the first message verbatim. A
        title somebody has seen and kept is not overwritten — renaming a conversation
        the reader recognises is worse than one clumsy row.
        """
        if thread.title in ("", "New conversation"):
            return True
        question = await self._first_question(thread)
        if not question:
            return False
        return thread.title == question.replace("\n", " ")[:_TITLE_CHARS]

    async def _name(self, thread: ChatThread, answer: str) -> None:
        """
        Title the thread from its first exchange.

        Never raises and never blocks the answer being stored: a conversation with a
        clumsy title is a small problem, and one that failed to save because naming it
        went wrong is a large one. The provisional title stays on any failure.
        """
        question = await self._first_question(thread)
        if not question:
            return

        try:
            from codelith.llm.client import chat_completion
            from codelith.llm.prompts.question_prompts import THREAD_TITLE
            from codelith.llm.router import select_spec

            raw = await chat_completion(
                messages=THREAD_TITLE.render(
                    question=question[:_TITLE_CONTEXT_CHARS],
                    answer=answer[:_TITLE_CONTEXT_CHARS],
                ),
                spec=select_spec("classify"),
            )
            title = _coerce_title(raw)
        except Exception as exc:
            logger.warning("thread_title_failed", thread_id=thread.id, error=str(exc))
            return

        if title:
            thread.title = title


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


def _coerce_title(raw: str | None) -> str:
    """The title out of the model's JSON, or `""` when there is nothing usable."""
    import json
    import re

    text = (raw or "").strip()
    if not text:
        return ""
    # Fenced JSON is common enough to be worth handling rather than losing the title.
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        title = json.loads(text).get("title", "")
    except Exception:
        title = text
    title = " ".join(str(title).split()).strip().strip("\"'").rstrip(".")
    # A title longer than the provisional one it replaces is not an improvement.
    return title[:_TITLE_CHARS] if 3 <= len(title) <= _TITLE_CHARS else ""
