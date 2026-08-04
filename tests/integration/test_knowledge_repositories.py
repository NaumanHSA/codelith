"""Knowledge Base repositories against a real Postgres."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import EntityKind, KBStatus, ModuleRole, NarrativeTopic
from app.languages.taxonomy import ModuleKind
from app.models.chunk import CodeChunk
from app.models.organization import Organization
from app.models.project import Project

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> Project:
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.flush()

    proj = Project(org_id=org.id, name="svc", slug=f"svc-{org.id}")
    db_session.add(proj)
    await db_session.flush()
    return proj


@pytest_asyncio.fixture
async def repos(db_session: AsyncSession) -> KnowledgeRepositories:
    return KnowledgeRepositories.for_session(db_session)


def _module(path: str, **over) -> dict:
    return {
        "path": path,
        "name": path.replace("/", "."),
        "kind": str(ModuleKind.PACKAGE),
        "role": str(ModuleRole.SERVICE),
        "language": "python",
        "file_count": 2,
        "loc": 120,
        "is_test": False,
        "symbols_json": [{"name": "run", "kind": "method", "line": 10}],
        "files_json": [f"{path}/a.py", f"{path}/b.py"],
        **over,
    }


class TestKnowledgeBaseLifecycle:
    async def test_start_build_creates_running_kb(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, commit_sha="abc123")

        assert kb.id is not None
        assert kb.status == KBStatus.RUNNING
        assert kb.commit_sha == "abc123"

    async def test_same_commit_reuses_the_row(self, repos, project) -> None:
        """Re-analysing a commit must not create a duplicate KB."""
        first = await repos.bases.start_build(project.id, "abc123")
        second = await repos.bases.start_build(project.id, "abc123")

        assert first.id == second.id
        assert len(await repos.bases.list_for_project(project.id)) == 1

    async def test_rebuild_clears_previous_children(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc123")
        await repos.modules.bulk_upsert(kb.id, [_module("app/one")])
        await repos.entities.bulk_add(kb.id, [{"kind": EntityKind.ROUTE, "name": "GET /x"}])

        await repos.bases.start_build(project.id, "abc123")  # rebuild

        assert await repos.modules.list_by_kb(kb.id) == []
        assert await repos.entities.list_by_kind(kb.id, EntityKind.ROUTE) == []

    async def test_finish_build_marks_ready_and_records_stats(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc123")

        done = await repos.bases.finish_build(
            kb.id, status=KBStatus.READY, stats={"modules": 4}
        )

        assert done.status == KBStatus.READY
        assert done.stats_json == {"modules": 4}
        assert done.completed_at is not None
        assert done.is_usable is True

    async def test_newer_build_supersedes_older(self, repos, project) -> None:
        old = await repos.bases.start_build(project.id, "commit-1")
        await repos.bases.finish_build(old.id)
        new = await repos.bases.start_build(project.id, "commit-2")
        await repos.bases.finish_build(new.id)

        latest = await repos.bases.get_latest_usable(project.id)
        assert latest.id == new.id
        assert (await repos.bases.get_by_id(old.id)).status == KBStatus.STALE

    async def test_degraded_is_still_usable(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.bases.finish_build(kb.id, status=KBStatus.DEGRADED, error="summaries failed")

        latest = await repos.bases.get_latest_usable(project.id)
        assert latest.id == kb.id
        assert latest.error_message == "summaries failed"

    async def test_failed_build_is_not_offered(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.bases.finish_build(kb.id, status=KBStatus.FAILED, error="boom")

        assert await repos.bases.get_latest_usable(project.id) is None

    async def test_never_analysed_project_returns_none(self, repos, project) -> None:
        assert await repos.bases.get_latest_usable(project.id) is None

    async def test_sourceless_project_uses_null_commit(self, repos, project) -> None:
        """Uploads have no commit; the row must still be findable."""
        kb = await repos.bases.start_build(project.id, commit_sha=None)
        assert (await repos.bases.get_by_commit(project.id, None)).id == kb.id


class TestModules:
    async def test_bulk_upsert_then_update(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")

        assert await repos.modules.bulk_upsert(kb.id, [_module("app/a"), _module("app/b")]) == 2
        # Same path again updates rather than duplicating.
        await repos.modules.bulk_upsert(kb.id, [_module("app/a", loc=999)])

        modules = await repos.modules.list_by_kb(kb.id)
        assert len(modules) == 2
        assert next(m for m in modules if m.path == "app/a").loc == 999

    async def test_summaries_are_written_per_module(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.modules.bulk_upsert(kb.id, [_module("app/a")])

        assert await repos.modules.count_missing_summaries(kb.id) == 1
        await repos.modules.set_summary(kb.id, "app/a", "Handles things.")

        assert (await repos.modules.get_by_path(kb.id, "app/a")).summary == "Handles things."
        assert await repos.modules.count_missing_summaries(kb.id) == 0

    async def test_tests_excluded_by_default(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.modules.bulk_upsert(
            kb.id,
            [
                _module("app/a"),
                _module("tests/unit", is_test=True, role=str(ModuleRole.TEST)),
            ],
        )

        assert len(await repos.modules.list_by_kb(kb.id)) == 1
        assert len(await repos.modules.list_by_kb(kb.id, include_tests=True)) == 2

    async def test_find_for_files_backs_the_writer_lookup(self, repos, project) -> None:
        """key_files → owning modules is how sections get pre-packed context."""
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.modules.bulk_upsert(kb.id, [_module("app/a"), _module("app/b")])

        found = await repos.modules.find_for_files(kb.id, ["app/a/b.py"])

        assert [m.path for m in found] == ["app/a"]

    async def test_role_breakdown(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.modules.bulk_upsert(
            kb.id,
            [_module("app/api", role=str(ModuleRole.API)), _module("app/svc")],
        )

        assert await repos.modules.role_breakdown(kb.id) == {"api": 1, "service": 1}


class TestEntitiesAndNarratives:
    async def test_entity_kind_breakdown_drives_suggestions(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.entities.bulk_add(
            kb.id,
            [
                {"kind": EntityKind.ROUTE, "name": "GET /a", "data_json": {"method": "GET"}},
                {"kind": EntityKind.ROUTE, "name": "POST /a"},
                {"kind": EntityKind.ENV_VAR, "name": "DATABASE_URL"},
            ],
        )

        assert await repos.entities.kind_breakdown(kb.id) == {"route": 2, "env_var": 1}

    async def test_entity_payload_is_schemaless(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.entities.bulk_add(
            kb.id,
            [{"kind": EntityKind.ROUTE, "name": "GET /x",
              "data_json": {"method": "GET", "handler": "get_x", "auth": True},
              "source_path": "app/api/v1/x.py", "source_line": 13}],
        )

        route = (await repos.entities.list_by_kind(kb.id, EntityKind.ROUTE))[0]
        assert route.data_json["handler"] == "get_x"
        assert route.source_line == 13

    async def test_narrative_upsert_replaces_topic(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")

        await repos.narratives.upsert(kb.id, NarrativeTopic.ARCHITECTURE, "v1")
        await repos.narratives.upsert(kb.id, NarrativeTopic.ARCHITECTURE, "v2")

        assert (await repos.narratives.get(kb.id, NarrativeTopic.ARCHITECTURE)).content_md == "v2"
        assert len(await repos.narratives.list_by_kb(kb.id)) == 1

    async def test_topics_present(self, repos, project) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.narratives.upsert(kb.id, NarrativeTopic.OVERVIEW, "o")
        await repos.narratives.upsert(kb.id, NarrativeTopic.AUTH, "a")

        assert await repos.narratives.topics_present(kb.id) == {"overview", "auth"}


class TestCascades:
    async def test_deleting_kb_removes_all_children(self, repos, project, db_session) -> None:
        kb = await repos.bases.start_build(project.id, "abc")
        await repos.modules.bulk_upsert(kb.id, [_module("app/a")])
        await repos.entities.bulk_add(kb.id, [{"kind": EntityKind.ROUTE, "name": "GET /x"}])
        await repos.narratives.upsert(kb.id, NarrativeTopic.OVERVIEW, "text")
        db_session.add(
            CodeChunk(
                project_id=project.id, kb_id=kb.id, source_path="a.py",
                chunk_type="code", content="x",
            )
        )
        await db_session.flush()

        await repos.bases.delete(kb.id)
        await db_session.flush()

        assert await repos.modules.list_by_kb(kb.id) == []
        assert await repos.entities.list_by_kind(kb.id, EntityKind.ROUTE) == []
        assert await repos.narratives.list_by_kb(kb.id) == []

    async def test_clear_children_also_drops_chunks(self, repos, project, db_session) -> None:
        """A rebuild must not leave last generation's embeddings behind."""
        kb = await repos.bases.start_build(project.id, "abc")
        db_session.add(
            CodeChunk(
                project_id=project.id, kb_id=kb.id, source_path="a.py",
                chunk_type="code", content="x",
            )
        )
        await db_session.flush()

        await repos.bases.clear_children(kb.id)

        from sqlalchemy import func, select

        remaining = await db_session.execute(
            select(func.count()).select_from(CodeChunk).where(CodeChunk.kb_id == kb.id)
        )
        assert remaining.scalar_one() == 0
