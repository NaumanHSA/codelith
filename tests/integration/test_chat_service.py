"""
Conversations, persisted.

A chat that loses what somebody typed because generation failed is the one thing it
must not do, so the user's turn is stored before the model is called. And a thread
that empties itself by disappearing would invalidate whatever the studio is holding
mid-session — clearing keeps the row.

These need a database. The answer path itself is tested without one in
`tests/unit/services/test_ask_service.py`; splitting them is why either can be
exercised in isolation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.apps.ask.threads import ChatService
from codelith.core.exceptions import NotFoundError
from codelith.models.organization import Organization
from codelith.models.project import Project


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> Project:
    """
    A project of its own, per test.

    Uniquely named rather than relying on the session rollback: `clear()` commits,
    because the endpoint that calls it has nothing further to do, and a committed
    row outlives the rollback the other fixtures depend on. A test whose isolation
    depends on nothing under test ever committing is a test that breaks the first
    time something legitimately does.
    """
    unique = uuid4().hex[:8]
    org = Organization(name=f"chat-org-{unique}", slug=f"chat-org-{unique}")
    db_session.add(org)
    await db_session.flush()
    proj = Project(org_id=org.id, name="chatty", slug=f"chatty-{unique}")
    db_session.add(proj)
    await db_session.flush()
    return proj


@pytest_asyncio.fixture
async def chat(db_session: AsyncSession) -> ChatService:
    return ChatService(db_session)


class TestThreads:
    async def test_a_thread_is_created_on_demand(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)

        assert thread.id
        assert thread.project_id == project.id

    async def test_an_existing_thread_is_reused(self, chat, project) -> None:
        first = await chat.get_or_create_thread(project.id, None, None)

        second = await chat.get_or_create_thread(project.id, first.id, None)

        assert second.id == first.id

    async def test_a_thread_from_another_project_reads_as_missing(
        self, chat, project, db_session
    ) -> None:
        """Scoped by project, so a wrong id is "no such conversation" rather than
        somebody else's."""
        other = Project(org_id=project.org_id, name="other", slug=f"other-{project.id}")
        db_session.add(other)
        await db_session.flush()
        thread = await chat.get_or_create_thread(other.id, None, None)

        with pytest.raises(NotFoundError):
            await chat.get_or_create_thread(project.id, thread.id, None)

    async def test_the_first_question_titles_the_thread(self, chat, project) -> None:
        """A list of rows all called "New conversation" is unusable, and asking the
        reader to name it is a chore nobody does."""
        thread = await chat.get_or_create_thread(project.id, None, None)

        await chat.add_user_message(thread, "How is the database initialised?")

        assert thread.title == "How is the database initialised?"

    async def test_a_later_question_does_not_retitle(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "first question")

        await chat.add_user_message(thread, "second question")

        assert thread.title == "first question"

    async def test_a_multiline_title_is_flattened_and_capped(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)

        await chat.add_user_message(thread, "line one\nline two " + "x" * 200)

        assert "\n" not in thread.title
        assert len(thread.title) <= 60


class TestMessages:
    async def test_a_turn_is_stored_with_its_token_count(self, chat, project) -> None:
        """Counted at write time so the context wheel is a sum over rows rather than
        a re-tokenisation of the whole conversation on every keystroke."""
        thread = await chat.get_or_create_thread(project.id, None, None)

        message = await chat.add_user_message(thread, "a question about the code")

        assert message.token_count > 0

    async def test_an_answer_keeps_its_evidence_and_citations(self, chat, project) -> None:
        """What it was answered from is a property of that moment: re-analysing the
        project changes what the same question would retrieve."""
        thread = await chat.get_or_create_thread(project.id, None, None)

        message = await chat.add_answer(
            thread,
            "The engine is built in `app/db/session.py:12-40`.",
            evidence={"counts": {"code": 6}, "routed_by": "llm"},
            citations=["app/db/session.py:12-40"],
            stripped=["app/ghost.py:1"],
        )

        assert message.evidence_json["counts"] == {"code": 6}
        assert message.citations_json == ["app/db/session.py:12-40"]
        assert message.stripped_json == ["app/ghost.py:1"]

    async def test_history_comes_back_oldest_first(self, chat, project) -> None:
        """The model reads it as a conversation, and a reversed one reads as the
        answer preceding its question."""
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "first")
        await chat.add_answer(thread, "answer one", evidence={}, citations=[], stripped=[])
        await chat.add_user_message(thread, "second")

        history = await chat.history(thread)

        assert [h["content"] for h in history] == ["first", "answer one", "second"]
        assert [h["role"] for h in history] == ["user", "assistant", "user"]

    async def test_the_token_total_sums_the_thread(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        a = await chat.add_user_message(thread, "a question")
        b = await chat.add_answer(thread, "an answer", evidence={}, citations=[], stripped=[])

        assert await chat.token_total(thread.id) == a.token_count + b.token_count


class TestReloadAndClear:
    async def test_a_conversation_survives_a_reload(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "what does this do")
        await chat.add_answer(thread, "it documents code", evidence={}, citations=[], stripped=[])

        loaded = await chat.load(project.id, thread.id)

        assert [m.content for m in loaded.messages] == ["what does this do", "it documents code"]

    async def test_the_most_recent_thread_is_the_one_offered(self, chat, project) -> None:
        older = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(older, "older")
        newer = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(newer, "newer")

        latest = await chat.latest(project.id)

        assert latest is not None
        assert latest.id == newer.id

    async def test_a_project_with_no_conversation_offers_none(self, chat, project) -> None:
        assert await chat.latest(project.id) is None

    async def test_clearing_empties_the_thread_but_keeps_it(self, chat, project) -> None:
        """Deleting the row would invalidate whatever the studio is holding and force
        it to reconcile a missing id mid-session."""
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "a question")
        await chat.add_answer(thread, "an answer", evidence={}, citations=[], stripped=[])

        removed = await chat.clear(project.id, thread.id)

        assert removed == 2
        reloaded = await chat.load(project.id, thread.id)
        assert reloaded.messages == []
        assert reloaded.title == "New conversation"
        assert await chat.token_total(thread.id) == 0

    async def test_clearing_an_unknown_thread_is_refused(self, chat, project) -> None:
        with pytest.raises(NotFoundError):
            await chat.clear(project.id, 999_999)


class TestTheRailsList:
    """
    What the sidebar shows. Flat and cross-project, because a list nested under
    whichever project happens to be selected is only reachable once you are already
    in the right place — the opposite of what "recent" is for.
    """

    async def test_a_thread_with_no_messages_is_not_listed(self, chat, project) -> None:
        """A thread exists from the moment somebody presses New chat. Listing an
        empty one would put a row called "New conversation" above the real ones
        every single time."""
        await chat.get_or_create_thread(project.id, None, None)

        rows = await chat.list_threads(project.org_id)

        assert rows == []

    async def test_a_listed_row_carries_its_project_and_count(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "what does this do")
        await chat.add_answer(thread, "it does things", evidence={}, citations=[], stripped=[])

        rows = await chat.list_threads(project.org_id)

        assert len(rows) == 1
        listed, count, project_name = rows[0]
        assert listed.id == thread.id
        assert count == 2
        assert project_name == project.name

    async def test_the_most_recent_conversation_is_first(self, chat, project) -> None:
        older = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(older, "asked first")
        newer = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(newer, "asked second")

        rows = await chat.list_threads(project.org_id)

        assert [t.id for t, _, _ in rows] == [newer.id, older.id]

    async def test_another_org_sees_nothing(self, chat, project) -> None:
        """The list is the one place a thread is reachable without naming its
        project, so it is the one place org scoping has to be got right."""
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "private question")

        assert await chat.list_threads(project.org_id + 9_999) == []


class TestDeletingAThread:
    async def test_delete_removes_the_thread_and_its_messages(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "a question")

        await chat.delete_thread(project.id, thread.id)

        with pytest.raises(NotFoundError):
            await chat.load(project.id, thread.id)
        assert await chat.list_threads(project.org_id) == []

    async def test_delete_is_scoped_to_the_project(self, chat, project, db_session) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)

        with pytest.raises(NotFoundError):
            await chat.delete_thread(project.id + 9_999, thread.id)


class TestMarkdownExport:
    """
    A conversation as a file somebody keeps. The point of exporting is to read it
    away from the studio, where a citation chip is not clickable and a list is.
    """

    async def test_questions_and_answers_both_survive(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "where is the entry point")
        await chat.add_answer(
            thread, "In `app/main.py`.", evidence={}, citations=["app/main.py:1-5"], stripped=[]
        )
        loaded = await chat.load(project.id, thread.id)

        md = ChatService.to_markdown(loaded, project.name)

        assert "# where is the entry point" in md
        assert "## where is the entry point" in md
        assert "In `app/main.py`." in md
        assert project.name in md

    async def test_citations_are_listed_under_the_answer(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "q")
        await chat.add_answer(
            thread, "a", evidence={}, citations=["app/db/session.py:12-40"], stripped=[]
        )
        loaded = await chat.load(project.id, thread.id)

        md = ChatService.to_markdown(loaded, project.name)

        assert "**Sources**" in md
        assert "`app/db/session.py:12-40`" in md

    async def test_unverified_references_are_named_not_dropped(self, chat, project) -> None:
        """An export that quietly drops them would be a cleaner document and a less
        honest one — the check having happened is part of what is being kept."""
        thread = await chat.get_or_create_thread(project.id, None, None)
        await chat.add_user_message(thread, "q")
        await chat.add_answer(
            thread, "a", evidence={}, citations=[], stripped=["app/ghost.py:1-2"]
        )
        loaded = await chat.load(project.id, thread.id)

        md = ChatService.to_markdown(loaded, project.name)

        assert "Unverified references" in md
        assert "`app/ghost.py:1-2`" in md

    async def test_an_empty_conversation_still_exports(self, chat, project) -> None:
        thread = await chat.get_or_create_thread(project.id, None, None)
        loaded = await chat.load(project.id, thread.id)

        md = ChatService.to_markdown(loaded, project.name)

        assert md.startswith("# ")
