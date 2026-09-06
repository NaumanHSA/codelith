"""
Drift, against a real database.

The unit tests pin the judgement — when a module has changed enough to mention, what
sentence a person reads. This pins the part that only a database can answer: two
knowledge bases of one project, at two commits, and the pages that cite code which
moved between them.

Worth stating because it surprised me while building it: **re-analysing the same
commit does not produce a second generation.** `uq_kb_project_commit` means one
knowledge base per commit, so a re-run upserts. Drift needs the code to have actually
moved, which is the right behaviour and not obvious from the outside.
"""

from __future__ import annotations

import uuid

import pytest

from codelith.apps.drift.service import DriftService
from codelith.knowledge.constants import KBStatus
from codelith.models.knowledge import KBEntity, KBModule, KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.site import DocPage, DocSite


@pytest.fixture
async def project(db_session):
    """
    A project of its own per test.

    Nothing here commits — the session rolls back at teardown — but the slugs are
    still unique, because a rollback does not undo a collision that already failed.
    """
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-drift-{tag}")
    db_session.add(org)
    await db_session.flush()
    p = Project(org_id=org.id, name="drifty", slug=f"drifty-{tag}")
    db_session.add(p)
    await db_session.flush()
    return p


async def _generation(
    db, project_id: int, sha: str, modules: list[dict], entities=(), architecture=None
):
    kb = KnowledgeBase(
        project_id=project_id,
        commit_sha=sha,
        status=KBStatus.READY,
        architecture_json=architecture or {},
    )
    db.add(kb)
    await db.flush()
    for m in modules:
        db.add(
            KBModule(
                kb_id=kb.id,
                path=m["path"],
                name=m.get("name", m["path"]),
                kind="package",
                role="service",
                loc=m.get("loc", 100),
                file_count=m.get("files", 2),
                symbols_json=m.get("symbols", [{"name": "run"}]),
                files_json=m.get("files_json", []),
            )
        )
    for e in entities:
        db.add(KBEntity(kb_id=kb.id, kind=e["kind"], name=e["name"], source_path=e.get("path")))
    await db.flush()
    return kb


class TestComparingTwoReadings:
    @pytest.mark.asyncio
    async def test_it_reports_what_moved(self, db_session, project) -> None:
        before = await _generation(
            db_session, project.id, "aaaaaaa",
            [
                {"path": "app/auth", "loc": 100},
                {"path": "app/legacy", "loc": 80},
                {"path": "app/stable", "loc": 50},
            ],
            entities=[{"kind": "route", "name": "GET /login", "path": "app/auth/routes.py"}],
        )
        after = await _generation(
            db_session, project.id, "bbbbbbb",
            [
                {"path": "app/auth", "loc": 180},          # grew
                {"path": "app/billing", "loc": 60},        # added
                {"path": "app/stable", "loc": 50},         # untouched
            ],
            entities=[{"kind": "route", "name": "GET /session", "path": "app/auth/routes.py"}],
        )

        report = await DriftService(db_session).compare(project.id, before.id, after.id)
        by_path = {m.path: m for m in report.modules}

        assert by_path["app/auth"].change == "grew"
        assert by_path["app/auth"].loc_delta == 80
        assert by_path["app/billing"].change == "added"
        assert by_path["app/legacy"].change == "removed"
        # A module that did not move must not appear at all — a report that lists
        # everything is a report nobody reads.
        assert "app/stable" not in by_path

        changes = {(e.name, e.change) for e in report.entities}
        assert ("GET /login", "removed") in changes
        assert ("GET /session", "added") in changes

    @pytest.mark.asyncio
    async def test_one_reading_is_not_comparable(self, db_session, project) -> None:
        await _generation(db_session, project.id, "only", [{"path": "app/a"}])
        assert await DriftService(db_session).latest_pair(project.id) is None

    @pytest.mark.asyncio
    async def test_the_pair_is_the_two_most_recent(self, db_session, project) -> None:
        await _generation(db_session, project.id, "one", [{"path": "a"}])
        second = await _generation(db_session, project.id, "two", [{"path": "a"}])
        third = await _generation(db_session, project.id, "three", [{"path": "a"}])

        pair = await DriftService(db_session).latest_pair(project.id)
        assert pair is not None
        assert (pair[0].id, pair[1].id) == (second.id, third.id), "oldest first"


class TestPagesThatAreNowWrong:
    """The reason the app exists. Everything else is context for this."""

    @pytest.mark.asyncio
    async def test_a_written_page_citing_changed_code_is_flagged(
        self, db_session, project
    ) -> None:
        site = DocSite(project_id=project.id, title="Docs", nav_json=[])
        db_session.add(site)
        await db_session.flush()

        db_session.add(
            DocPage(
                site_id=site.id, section_slug="api", slug="auth", title="Authentication",
                doc_type="api", status="ready", order_index=0,
                content_markdown="Auth works like this.",
                source_files_json=["app/auth/routes.py"],
            )
        )
        # A page about code that did not move must not be flagged.
        db_session.add(
            DocPage(
                site_id=site.id, section_slug="api", slug="stable", title="Stable",
                doc_type="api", status="ready", order_index=1,
                content_markdown="This is unchanged.",
                source_files_json=["app/stable/thing.py"],
            )
        )
        # A planned page cannot be wrong about anything yet.
        db_session.add(
            DocPage(
                site_id=site.id, section_slug="api", slug="planned", title="Planned",
                doc_type="api", status="planned", order_index=2,
                content_markdown=None,
                source_files_json=["app/auth/routes.py"],
            )
        )
        await db_session.flush()

        before = await _generation(
            db_session, project.id, "aaa",
            [{"path": "app/auth", "symbols": [{"name": "login"}]}, {"path": "app/stable"}],
        )
        after = await _generation(
            db_session, project.id, "bbb",
            [{"path": "app/auth", "symbols": [{"name": "authenticate"}]}, {"path": "app/stable"}],
        )

        report = await DriftService(db_session).compare(project.id, before.id, after.id)
        flagged = {p.address for p in report.pages_at_risk}

        assert flagged == {"api/auth"}, "only the written page citing moved code"
        risk = report.pages_at_risk[0]
        assert risk.changed_files == ["app/auth/routes.py"]
        assert "replaced" in risk.reason
        assert "written page(s) now describe code that moved" in report.summary()

    @pytest.mark.asyncio
    async def test_a_project_with_no_site_is_not_an_error(self, db_session, project) -> None:
        before = await _generation(db_session, project.id, "aaa", [{"path": "app/a", "loc": 10}])
        after = await _generation(db_session, project.id, "bbb", [{"path": "app/a", "loc": 90}])

        report = await DriftService(db_session).compare(project.id, before.id, after.id)
        assert report.modules and report.pages_at_risk == []


def _map(*names, relations=(), types=None):
    """An `architecture_json` column, in the shape the writer actually stores."""
    types = types or {}
    return {
        "services": [{"name": n, "type": types.get(n, "service")} for n in names],
        "relations": [
            {"from": a, "to": b, "kind": k} for a, b, k in relations
        ],
    }


class TestComparingTwoArchitectures:
    """
    The shape of the system, diffed.

    The unit tests pin the rules. This pins the part only a database answers: that
    the column round-trips through JSON storage and comes back as something
    comparable, and that the guard survives a real row rather than a literal.
    """

    @pytest.mark.asyncio
    async def test_a_service_appeared_and_a_connection_broke(self, db_session, project) -> None:
        before = await _generation(
            db_session, project.id, "ccccccc", [{"path": "app/a"}],
            architecture=_map("api", "cache", relations=[("api", "cache", "reads")]),
        )
        after = await _generation(
            db_session, project.id, "ddddddd", [{"path": "app/a"}],
            architecture=_map("api", "worker", relations=[("api", "worker", "queues")]),
        )

        report = await DriftService(db_session).compare(project.id, before.id, after.id)

        assert report.architecture_comparable is True
        changes = {s.name: s.change for s in report.services}
        assert changes == {"worker": "added", "cache": "removed"}
        edges = {(r.source, r.target): r.change for r in report.relations}
        assert edges == {("api", "cache"): "removed", ("api", "worker"): "added"}
        assert "1 service(s) appeared" in report.summary()
        assert "1 connection(s) broke" in report.summary()

    @pytest.mark.asyncio
    async def test_a_reading_with_no_map_claims_nothing(self, db_session, project) -> None:
        """
        Every knowledge base written before the architecture agent landed has `{}` in
        this column, and on this machine that is all of them. Diffing a map against
        an empty one would report every service as newly added.
        """
        before = await _generation(db_session, project.id, "eeeeeee", [{"path": "app/a"}])
        after = await _generation(
            db_session, project.id, "fffffff", [{"path": "app/a"}],
            architecture=_map("api", "worker"),
        )

        report = await DriftService(db_session).compare(project.id, before.id, after.id)

        assert report.architecture_comparable is False
        assert report.services == [] and report.relations == []

    @pytest.mark.asyncio
    async def test_a_rewiring_with_no_module_movement_is_not_an_empty_report(
        self, db_session, project
    ) -> None:
        """
        The case the old `is_empty` got wrong. A release that moved no module but
        rewired two services would have said "nothing structural changed" while the
        diagram was different.
        """
        modules = [{"path": "app/a", "loc": 100}]
        before = await _generation(
            db_session, project.id, "1111111", modules,
            architecture=_map("api", "db", relations=[("api", "db", "reads")]),
        )
        after = await _generation(
            db_session, project.id, "2222222", modules,
            architecture=_map("api", "db", relations=[("api", "db", "writes")]),
        )

        report = await DriftService(db_session).compare(project.id, before.id, after.id)

        assert report.modules == []
        assert report.is_empty is False
        assert [r.change for r in report.relations] == ["reworded"]
