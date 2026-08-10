"""
The merge that makes incremental growth safe.

Analysis re-plans the whole site on every commit; composition fills it in a section
at a time, possibly months apart. Every test here is a way that could go wrong:

  * a re-analysis that renames a slug breaks bookmarks and internal links
  * a re-analysis that churns rows destroys the provenance S5 depends on
  * a re-analysis that deletes a page loses written work
  * a merge that overrides a hand-edited nav makes the user's edits pointless
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.constants import PageStatus
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.features.documentation.services.site_service import SiteService


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> Project:
    tag = uuid4().hex[:8]
    org = Organization(name="Acme", slug=f"acme-{tag}")
    db_session.add(org)
    await db_session.flush()

    project = Project(org_id=org.id, name="widgets", slug=f"widgets-{tag}")
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, project: Project) -> User:
    """A member of the project's org — `get_site` authorises before it reads."""
    member = User(
        org_id=project.org_id,
        email=f"reader-{uuid4().hex[:8]}@example.com",
        password_hash="x",
        role="user",
    )
    db_session.add(member)
    await db_session.flush()
    return member


@pytest.fixture
def service(db_session: AsyncSession) -> SiteService:
    return SiteService(db_session)


def page(slug: str, title: str, order: int = 0, **kw) -> dict:
    return {
        "slug": slug,
        "title": title,
        "doc_type": "api",
        "intent": f"Covers {title}.",
        "key_files": ["app/api/routes.py"],
        "confidence": 0.8,
        "reason": "12 routes detected",
        "order_index": order,
        **kw,
    }


def site_map(*sections: dict, title: str = "widgets") -> dict:
    return {"title": title, "sections": list(sections)}


def section(slug: str, title: str, *pages: dict) -> dict:
    return {"slug": slug, "title": title, "order_index": 0, "pages": list(pages)}


API = section(
    "api", "API Reference", page("overview", "Overview"), page("endpoints", "Endpoints", 1)
)


class TestFirstMerge:
    async def test_it_creates_the_site_and_plans_every_page(
        self, service: SiteService, project: Project
    ) -> None:
        counts = await service.merge_proposal(project.id, site_map(API))

        assert (counts.inserted, counts.orphaned, counts.sections) == (2, 0, 1)
        pages = await service.pages.list_for_site(counts.site_id)
        assert [p.slug for p in pages] == ["overview", "endpoints"]
        assert {p.status for p in pages} == {PageStatus.PLANNED}

    async def test_it_records_the_planner_evidence(
        self, service: SiteService, project: Project
    ) -> None:
        """`key_files` and `reason` are what make a proposed page auditable."""
        counts = await service.merge_proposal(project.id, site_map(API))
        first = (await service.pages.list_for_site(counts.site_id))[0]

        assert first.key_files_json == ["app/api/routes.py"]
        assert first.confidence == 0.8
        assert first.reason == "12 routes detected"

    async def test_the_nav_follows_the_proposal(
        self, service: SiteService, project: Project
    ) -> None:
        counts = await service.merge_proposal(
            project.id, site_map(API, section("guides", "Guides", page("setup", "Setup")))
        )
        site = await service.sites.get_by_id(counts.site_id)

        assert [e["slug"] for e in site.nav_json] == ["api", "guides"]

    async def test_an_empty_proposal_is_a_no_op(
        self, service: SiteService, project: Project
    ) -> None:
        """A failed planning call must not retire a site that is already written."""
        await service.merge_proposal(project.id, site_map(API))
        counts = await service.merge_proposal(project.id, site_map())

        assert (counts.inserted, counts.orphaned, counts.updated) == (0, 0, 0)
        site = await service.sites.get_for_project(project.id)
        assert len(await service.pages.list_for_site(site.id)) == 2


class TestIdempotence:
    async def test_merging_the_same_map_twice_changes_nothing(
        self, service: SiteService, project: Project
    ) -> None:
        """
        Analysis runs on every commit. A merge that churned rows would bump
        `updated_at` on pages nobody touched and make S5's staleness meaningless.
        """
        await service.merge_proposal(project.id, site_map(API))
        second = await service.merge_proposal(project.id, site_map(API))

        assert (second.inserted, second.updated, second.orphaned) == (0, 0, 0)
        assert second.total_pages == 2

    async def test_a_third_merge_is_also_clean(
        self, service: SiteService, project: Project
    ) -> None:
        for _ in range(3):
            counts = await service.merge_proposal(project.id, site_map(API))
        assert (counts.inserted, counts.updated) == (0, 0)


class TestSlugStability:
    async def test_a_retitled_page_keeps_its_slug(
        self, service: SiteService, project: Project
    ) -> None:
        """Slugs are URLs and internal link targets. Titles are not."""
        first = await service.merge_proposal(project.id, site_map(API))
        renamed = section(
            "api", "API Reference",
            page("overview", "What This API Does"),
            page("endpoints", "Endpoints", 1),
        )
        await service.merge_proposal(project.id, site_map(renamed))

        pages = {p.slug: p for p in await service.pages.list_for_site(first.site_id)}
        assert set(pages) == {"overview", "endpoints"}
        assert pages["overview"].title == "What This API Does"

    async def test_re_analysis_of_a_changed_repo_never_renames_a_slug(
        self, service: SiteService, project: Project
    ) -> None:
        """
        The repository moved on: new intent, new anchor files, new page. The pages
        that survive keep their identity and their row.
        """
        first = await service.merge_proposal(project.id, site_map(API))
        before = {p.slug: p.id for p in await service.pages.list_for_site(first.site_id)}

        grown = section(
            "api", "API Reference",
            page("overview", "Overview", intent="Rewritten after the refactor."),
            page("endpoints", "Endpoints", 1, key_files=["app/api/v2.py"]),
            page("webhooks", "Webhooks", 2),
        )
        counts = await service.merge_proposal(project.id, site_map(grown))

        after = {p.slug: p.id for p in await service.pages.list_for_site(first.site_id)}
        assert counts.inserted == 1 and counts.orphaned == 0
        assert all(after[slug] == page_id for slug, page_id in before.items())

    async def test_the_same_slug_in_two_sections_is_two_pages(
        self, service: SiteService, project: Project
    ) -> None:
        """Uniqueness is per section — `api/overview` and `guides/overview` differ."""
        counts = await service.merge_proposal(
            project.id,
            site_map(
                section("api", "API", page("overview", "Overview")),
                section("guides", "Guides", page("overview", "Overview")),
            ),
        )
        assert counts.inserted == 2


class TestOrphaning:
    async def test_a_page_no_longer_proposed_is_orphaned_not_deleted(
        self, service: SiteService, project: Project
    ) -> None:
        first = await service.merge_proposal(project.id, site_map(API))
        counts = await service.merge_proposal(
            project.id, site_map(section("api", "API Reference", page("overview", "Overview")))
        )

        assert counts.orphaned == 1
        pages = {p.slug: p for p in await service.pages.list_for_site(first.site_id)}
        assert pages["endpoints"].status == PageStatus.ORPHANED

    async def test_an_orphan_keeps_its_content(
        self, service: SiteService, project: Project
    ) -> None:
        """Orphaning is about the nav. Written prose is never thrown away."""
        first = await service.merge_proposal(project.id, site_map(API))
        written = await service.pages.get_by_slug(first.site_id, "api", "endpoints")
        written.content_markdown = "# Endpoints\n\nReal prose."
        written.status = PageStatus.READY
        await service.db.flush()

        await service.merge_proposal(
            project.id, site_map(section("api", "API Reference", page("overview", "Overview")))
        )

        assert written.status == PageStatus.ORPHANED
        assert written.content_markdown == "# Endpoints\n\nReal prose."

    async def test_orphaning_is_not_repeated_on_the_next_merge(
        self, service: SiteService, project: Project
    ) -> None:
        reduced = site_map(section("api", "API Reference", page("overview", "Overview")))
        await service.merge_proposal(project.id, site_map(API))
        await service.merge_proposal(project.id, reduced)
        counts = await service.merge_proposal(project.id, reduced)

        assert (counts.orphaned, counts.updated, counts.inserted) == (0, 0, 0)

    async def test_a_reproposed_orphan_comes_back(
        self, service: SiteService, project: Project
    ) -> None:
        """One bad planning run must not permanently retire a page."""
        first = await service.merge_proposal(project.id, site_map(API))
        await service.merge_proposal(
            project.id, site_map(section("api", "API Reference", page("overview", "Overview")))
        )
        counts = await service.merge_proposal(project.id, site_map(API))

        restored = await service.pages.get_by_slug(first.site_id, "api", "endpoints")
        assert counts.restored == 1
        assert restored.status == PageStatus.PLANNED

    async def test_a_reproposed_orphan_with_prose_returns_ready(
        self, service: SiteService, project: Project
    ) -> None:
        first = await service.merge_proposal(project.id, site_map(API))
        written = await service.pages.get_by_slug(first.site_id, "api", "endpoints")
        written.content_markdown = "# Endpoints"
        await service.db.flush()

        await service.merge_proposal(
            project.id, site_map(section("api", "API Reference", page("overview", "Overview")))
        )
        await service.merge_proposal(project.id, site_map(API))

        assert written.status == PageStatus.READY

    async def test_a_section_that_lost_every_page_leaves_the_nav(
        self, service: SiteService, project: Project
    ) -> None:
        counts = await service.merge_proposal(
            project.id, site_map(API, section("guides", "Guides", page("setup", "Setup")))
        )
        await service.merge_proposal(project.id, site_map(API))

        site = await service.sites.get_by_id(counts.site_id)
        assert [e["slug"] for e in site.nav_json] == ["api"]


class TestPinning:
    async def test_a_pinned_page_keeps_its_title_and_order(
        self, service: SiteService, project: Project
    ) -> None:
        """Re-analysis may not undo a user's edit to the nav."""
        first = await service.merge_proposal(project.id, site_map(API))
        pinned = await service.pages.get_by_slug(first.site_id, "api", "overview")
        pinned.title = "Start Here"
        pinned.order_index = 9
        pinned.pinned = True
        await service.db.flush()

        await service.merge_proposal(project.id, site_map(API))

        assert (pinned.title, pinned.order_index) == ("Start Here", 9)

    async def test_a_pinned_page_survives_falling_out_of_the_proposal(
        self, service: SiteService, project: Project
    ) -> None:
        first = await service.merge_proposal(project.id, site_map(API))
        pinned = await service.pages.get_by_slug(first.site_id, "api", "endpoints")
        pinned.pinned = True
        await service.db.flush()

        counts = await service.merge_proposal(
            project.id, site_map(section("api", "API Reference", page("overview", "Overview")))
        )

        assert counts.orphaned == 0
        assert pinned.status == PageStatus.PLANNED

    async def test_a_pinned_page_still_takes_new_planner_evidence(
        self, service: SiteService, project: Project
    ) -> None:
        """Pinning protects the *nav*, not the page's grounding."""
        first = await service.merge_proposal(project.id, site_map(API))
        pinned = await service.pages.get_by_slug(first.site_id, "api", "overview")
        pinned.pinned = True
        await service.db.flush()

        await service.merge_proposal(
            project.id,
            site_map(
                section("api", "API Reference",
                        page("overview", "Overview", key_files=["app/api/v2.py"]),
                        page("endpoints", "Endpoints", 1))
            ),
        )

        assert pinned.key_files_json == ["app/api/v2.py"]

    async def test_a_pinned_section_keeps_its_title(
        self, service: SiteService, project: Project
    ) -> None:
        counts = await service.merge_proposal(project.id, site_map(API))
        site = await service.sites.get_by_id(counts.site_id)
        site.nav_json = [{**site.nav_json[0], "title": "The API", "pinned": True}]
        await service.db.flush()

        await service.merge_proposal(project.id, site_map(API))

        assert site.nav_json[0]["title"] == "The API"

    async def test_a_pinned_pages_section_stays_reachable(
        self, service: SiteService, project: Project
    ) -> None:
        """A surviving page whose section left the proposal must still have a nav entry."""
        counts = await service.merge_proposal(
            project.id, site_map(API, section("guides", "Guides", page("setup", "Setup")))
        )
        pinned = await service.pages.get_by_slug(counts.site_id, "guides", "setup")
        pinned.pinned = True
        await service.db.flush()

        await service.merge_proposal(project.id, site_map(API))

        site = await service.sites.get_by_id(counts.site_id)
        assert [e["slug"] for e in site.nav_json] == ["api", "guides"]


class TestReadModel:
    async def test_it_returns_the_map_grouped_by_section(
        self, service: SiteService, project: Project, user: User
    ) -> None:
        await service.merge_proposal(
            project.id, site_map(API, section("guides", "Guides", page("setup", "Setup")))
        )

        out = await service.get_site(project.id, user)

        assert [s.slug for s in out.sections] == ["api", "guides"]
        assert [p.slug for p in out.sections[0].pages] == ["overview", "endpoints"]
        assert out.page_counts == {PageStatus.PLANNED: 3}

    async def test_it_carries_provenance_and_evidence(
        self, service: SiteService, project: Project, user: User
    ) -> None:
        """One call has to be enough to draw the nav *and* explain it."""
        await service.merge_proposal(project.id, site_map(API))

        first = (await service.get_site(project.id, user)).sections[0].pages[0]

        assert first.key_files == ["app/api/routes.py"]
        assert first.source_files == []
        assert first.reason == "12 routes detected"

    async def test_orphans_are_returned_separately(
        self, service: SiteService, project: Project, user: User
    ) -> None:
        await service.merge_proposal(project.id, site_map(API))
        await service.merge_proposal(
            project.id, site_map(section("api", "API Reference", page("overview", "Overview")))
        )

        out = await service.get_site(project.id, user)

        assert [p.slug for p in out.sections[0].pages] == ["overview"]
        assert [p.slug for p in out.orphaned_pages] == ["endpoints"]

    async def test_a_project_with_no_site_returns_none(
        self, service: SiteService, project: Project, user: User
    ) -> None:
        assert await service.get_site(project.id, user) is None
