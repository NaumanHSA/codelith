"""
The Documentation dashboard's numbers, counted on the server.

Pins the three things a count can quietly get wrong: frozen versions must not be
counted as live pages, an out-of-date page is still a written one, and another
organisation's codebases are invisible.
"""

from __future__ import annotations

import uuid

import pytest

from codelith.apps.documentation.services.overview_service import DocumentationOverview
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.site import DocPage, DocSite, DocSiteVersion
from codelith.models.user import User


async def _codebase(db, org_id: int, name: str) -> tuple[Project, DocSite]:
    project = Project(org_id=org_id, name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()
    site = DocSite(project_id=project.id, title=name)
    db.add(site)
    await db.flush()
    return project, site


def _page(site: DocSite, slug: str, status: str, words: int = 0, version_id: int | None = None) -> DocPage:
    return DocPage(
        site_id=site.id, version_id=version_id, section_slug="guide", slug=slug, title=slug,
        doc_type="guide", status=status, word_count=words,
        content_markdown="text" if status in ("ready", "stale") else None,
    )


@pytest.mark.asyncio
async def test_counts_live_pages_by_state_for_this_organisation(db_session) -> None:
    tag = uuid.uuid4().hex[:8]
    mine, theirs = Organization(name="a", slug=f"a-{tag}"), Organization(name="b", slug=f"b-{tag}")
    db_session.add_all([mine, theirs])
    await db_session.flush()
    user = User(email=f"u-{tag}@example.com", password_hash="x", full_name="u", org_id=mine.id, role="admin")
    db_session.add(user)

    project, site = await _codebase(db_session, mine.id, "alpha")
    other, other_site = await _codebase(db_session, theirs.id, "beta")
    version = DocSiteVersion(site_id=site.id, label="v1")
    db_session.add(version)
    await db_session.flush()

    db_session.add_all(
        [
            _page(site, "a", "ready", 120),
            _page(site, "b", "stale", 80),
            _page(site, "c", "planned"),
            _page(site, "d", "planned"),
            _page(site, "frozen", "ready", 999, version_id=version.id),  # a snapshot, not live
            _page(other_site, "x", "ready", 50),
        ]
    )
    await db_session.flush()

    rows = {r.project_id: r for r in await DocumentationOverview(db_session).for_user(user)}

    assert other.id not in rows
    alpha = rows[project.id]
    assert alpha.pages == {"ready": 1, "stale": 1, "planned": 2}
    assert (alpha.total, alpha.written, alpha.words) == (4, 2, 200)
    assert alpha.versions == 1
    assert alpha.last_written_at is not None
    assert alpha.published is None
