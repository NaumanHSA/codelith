"""
Publishing, end to end, against a real database and a real directory.

The unit tests pin the pieces: what the hash covers, what the verifier refuses, what
the renderer writes. This pins the part only a database and a filesystem can answer.

Four properties, and each one is a promise made to somebody:

  * **A published site is reachable at its URL**, by a request carrying no session,
    because the people it is shared with do not have one.
  * **Publishing twice with nothing changed builds nothing.** That is what makes
    Publish safe to press.
  * **Taking it down takes it down**, immediately, and the files go with it.
  * **A build that fails never becomes the site.** Whatever was live stays live.
"""

from __future__ import annotations

import uuid

import pytest

from codelith.apps.documentation.publishing import paths
from codelith.apps.documentation.services.publication_service import PublicationService
from codelith.knowledge.constants import PageStatus
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.publication import BuildStatus, PublicationStatus
from codelith.models.site import DocPage, DocSite
from codelith.models.user import User


@pytest.fixture
async def scene(db_session, tmp_path, monkeypatch):
    """
    A project with a two-page site, a store of its own on disk, and a worker that
    talks to the test database.

    The task opens its own session, which is right in production and wrong here: it
    would reach the real database rather than this one. Pointing `AsyncSessionLocal`
    at the test engine keeps the task's code path exactly as it ships, which is the
    part worth exercising.
    """
    from tests.integration.conftest import TestSessionLocal

    monkeypatch.setattr(
        "codelith.apps.documentation.publishing.paths.storage_base",
        lambda: (tmp_path / "store").resolve(),
    )
    monkeypatch.setattr(
        "codelith.apps.documentation.tasks.publish_tasks.AsyncSessionLocal", TestSessionLocal
    )

    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-pub-{tag}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email=f"pub-{tag}@example.com",
        password_hash="x",
        full_name="Publisher",
        org_id=org.id,
        role="admin",
        is_active=True,
    )
    project = Project(org_id=org.id, name="Neurosurfer", slug=f"neuro-{tag}")
    db_session.add_all([user, project])
    await db_session.flush()

    site = DocSite(
        project_id=project.id,
        title="Neurosurfer",
        nav_json=[{"slug": "guides", "title": "Guides", "order_index": 0}],
    )
    db_session.add(site)
    await db_session.flush()

    for i, (slug, title) in enumerate([("getting-started", "Getting started"), ("arch", "Architecture")]):
        db_session.add(
            DocPage(
                site_id=site.id,
                section_slug="guides",
                slug=slug,
                title=title,
                doc_type="architecture",
                status=PageStatus.READY,
                content_markdown=f"# {title}\n\nProse for {title}.",
                order_index=i,
                commit_sha="4865c2f",
            )
        )
    await db_session.flush()
    return {"user": user, "project": project, "site": site, "tmp": tmp_path}


async def _build(db_session, scene, **kw):
    """Prepare and run one publish, the way the endpoint and the worker do together."""
    from codelith.apps.documentation.tasks.publish_tasks import _publish
    from codelith.models.job import Job

    service = PublicationService(db_session)
    prepared = await service.prepare(scene["project"].id, scene["user"], **kw)
    if prepared["unchanged"]:
        return prepared, None

    job = Job(project_id=scene["project"].id, job_type="publish", status="pending")
    db_session.add(job)
    await db_session.flush()
    prepared["build"].job_id = job.id
    await db_session.commit()

    # The task opens its own session, as it does in production, and commits from it,
    # so these two rows are stale here until re-read. Only these two: expiring the
    # whole identity map would also expire the `user`, and reloading that lazily is
    # exactly the thing an async session refuses to do.
    await _publish(job.id, prepared["publication"].id, prepared["build"].id)
    await db_session.refresh(prepared["publication"])
    await db_session.refresh(prepared["build"])
    return prepared, job


class TestPublishing:
    async def test_a_site_is_built_and_becomes_live(self, db_session, scene):
        prepared, _ = await _build(db_session, scene)
        pub = prepared["publication"]
        await db_session.refresh(pub)

        assert pub.status == PublicationStatus.LIVE
        assert pub.current_build_id == prepared["build"].id

        root = paths.storage_base() / prepared["build"].storage_path
        assert (root / "index.html").is_file()
        assert prepared["build"].status == BuildStatus.SUCCEEDED
        assert prepared["build"].page_count == 2

    async def test_the_url_is_a_capability(self, db_session, scene):
        prepared, _ = await _build(db_session, scene)
        slug = prepared["publication"].slug
        assert slug.startswith("neurosurfer-")
        assert len(slug.rsplit("-", 1)[1]) == 32

    async def test_publishing_again_unchanged_builds_nothing(self, db_session, scene):
        first, _ = await _build(db_session, scene)
        again = await PublicationService(db_session).prepare(
            scene["project"].id, scene["user"]
        )
        assert again["unchanged"] is True
        assert again["build"] is None
        assert again["publication"].id == first["publication"].id

    async def test_force_rebuilds_the_same_address(self, db_session, scene):
        first, _ = await _build(db_session, scene)
        second, _ = await _build(db_session, scene, force=True)

        assert second["publication"].id == first["publication"].id, "the link must not change"
        assert second["build"].id != first["build"].id
        assert second["publication"].current_build_id == second["build"].id

    async def test_a_changed_page_is_no_longer_unchanged(self, db_session, scene):
        await _build(db_session, scene)
        # Scoped to this test's own site. The task commits, so rows from every other
        # test in the file are still in the database when this one runs.
        from sqlalchemy import select

        page = (await db_session.execute(
            select(DocPage).where(
                DocPage.site_id == scene["site"].id, DocPage.slug == "arch"
            )
        )).scalar_one()
        page.content_markdown = "# Architecture\n\nCompletely different prose."
        await db_session.commit()

        again = await PublicationService(db_session).prepare(scene["project"].id, scene["user"])
        assert again["unchanged"] is False

    async def test_taking_it_down_removes_the_files_and_the_pointer(self, db_session, scene):
        prepared, _ = await _build(db_session, scene)
        pub_id = prepared["publication"].id
        root = paths.publication_dir(pub_id)
        assert root.exists()

        pub = await PublicationService(db_session).unpublish(pub_id, scene["user"])
        assert pub.status == PublicationStatus.UNPUBLISHED
        assert pub.current_build_id is None
        assert not root.exists()

    async def test_rollback_returns_to_the_previous_build(self, db_session, scene):
        first, _ = await _build(db_session, scene)
        first_build_id = first["build"].id
        second, _ = await _build(db_session, scene, force=True)
        assert second["publication"].current_build_id != first_build_id

        pub = await PublicationService(db_session).rollback(second["publication"].id, scene["user"])
        assert pub.current_build_id == first_build_id
        assert pub.status == PublicationStatus.LIVE

    async def test_rotating_changes_the_address(self, db_session, scene):
        prepared, _ = await _build(db_session, scene)
        before = prepared["publication"].slug
        pub = await PublicationService(db_session).rotate(prepared["publication"].id, scene["user"])
        assert pub.slug != before

    async def test_an_empty_site_is_refused_rather_than_published_blank(
        self, db_session, scene
    ):
        from codelith.core.exceptions import ValidationError
        from sqlalchemy import delete

        await db_session.execute(delete(DocPage).where(DocPage.site_id == scene["site"].id))
        await db_session.commit()

        with pytest.raises(ValidationError, match="nothing written"):
            await PublicationService(db_session).prepare(scene["project"].id, scene["user"])

    async def test_a_failed_build_leaves_the_live_one_serving(self, db_session, scene, monkeypatch):
        """
        The property the whole pointer design exists for. A build that blows up must
        not take down the site somebody has already shared.
        """
        first, _ = await _build(db_session, scene)
        live_build_id = first["publication"].current_build_id

        from codelith.apps.documentation.publishing.renderers import BuiltinRenderer

        def explode(self, tree, out_dir):
            raise RuntimeError("renderer fell over")

        monkeypatch.setattr(BuiltinRenderer, "build", explode)

        with pytest.raises(RuntimeError):
            await _build(db_session, scene, force=True)

        await db_session.refresh(first["publication"])
        assert first["publication"].status == PublicationStatus.LIVE
        assert first["publication"].current_build_id == live_build_id
