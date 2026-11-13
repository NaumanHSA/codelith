"""
The server reads a local codebase again after each commit, when asked to — and stays
quiet otherwise: no reading for a commit already read, none while one is running, and
a commit is tried once rather than every few seconds for ever.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from codelith.models.job import Job
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project, ProjectSource
from codelith.models.user import User
from codelith.services import auto_read


@pytest.fixture(autouse=True)
def fresh_memory():
    auto_read._attempted.clear()
    yield
    auto_read._attempted.clear()


async def codebase(db, *, source_type="local", read_at="aaa"):
    tag = uuid.uuid4().hex[:6]
    org = Organization(name="o", slug=f"o-{tag}")
    db.add(org)
    await db.flush()
    user = User(email=f"u-{tag}@example.com", password_hash="x", full_name="u", org_id=org.id, role="admin")
    project = Project(org_id=org.id, name="app", slug=f"app-{tag}")
    db.add_all([user, project])
    await db.flush()
    source = ProjectSource(project_id=project.id, source_type=source_type, url_or_path="/repo", config_json={})
    db.add(source)
    if read_at:
        db.add(KnowledgeBase(project_id=project.id, commit_sha=read_at, status="ready"))
    await db.flush()
    return user, project, source


@pytest.fixture
def started(monkeypatch):
    calls: list[tuple[int, bool]] = []

    async def start(self, project_id, user, force=False):
        calls.append((project_id, force))
        return type("J", (), {"id": len(calls)})()

    monkeypatch.setattr("codelith.services.knowledge_service.KnowledgeService.start_analysis", start)
    return calls


def at(sha):
    return lambda _path: sha


class TestTheLoop:
    async def test_off_by_default(self, db_session, started) -> None:
        await codebase(db_session)
        assert await auto_read.tick(db_session, head=at("bbb")) == []
        assert started == []

    async def test_a_new_commit_starts_one_incremental_reading(self, db_session, started) -> None:
        user, project, source = await codebase(db_session)
        source.config_json = auto_read.switch(source, True, user.id)
        await db_session.flush()

        assert await auto_read.tick(db_session, head=at("bbb")) == [project.id]
        assert started == [(project.id, False)]  # never from scratch
        # Asked again for the same commit: already handed over.
        assert await auto_read.tick(db_session, head=at("bbb")) == []

    async def test_the_commit_already_read_starts_nothing(self, db_session, started) -> None:
        user, _project, source = await codebase(db_session, read_at="bbb")
        source.config_json = auto_read.switch(source, True, user.id)
        await db_session.flush()
        assert await auto_read.tick(db_session, head=at("bbb")) == []

    async def test_it_waits_for_a_reading_already_running(self, db_session, started) -> None:
        user, project, source = await codebase(db_session)
        source.config_json = auto_read.switch(source, True, user.id)
        db_session.add(Job(project_id=project.id, job_type="analysis", status="running", config_json={}))
        await db_session.flush()
        assert await auto_read.tick(db_session, head=at("bbb")) == []
        assert started == []


class TestTheSwitch:
    async def test_switching_on_records_who_and_when(self, db_session, monkeypatch) -> None:
        user, project, source = await codebase(db_session)

        async def allowed(self, project_id, user):
            return project

        monkeypatch.setattr("codelith.services.project_service.ProjectService.get", allowed)
        state = await auto_read.set_auto_read(db_session, project.id, user, True)
        assert state["available"] and state["on"] and state["since"]
        assert source.config_json["auto_read"]["by"] == user.id

    async def test_a_hosted_repository_is_refused_with_what_to_do_instead(self, db_session, monkeypatch) -> None:
        user, project, _source = await codebase(db_session, source_type="github")

        async def allowed(self, project_id, user):
            return project

        monkeypatch.setattr("codelith.services.project_service.ProjectService.get", allowed)
        with pytest.raises(HTTPException) as err:
            await auto_read.set_auto_read(db_session, project.id, user, True)
        assert err.value.status_code == 422
        assert "codelith watch" in err.value.detail
