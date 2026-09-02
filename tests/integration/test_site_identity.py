"""
Whether a second analysis recognises the site it already wrote.

This is the failure it exists for, observed on a real project: analysis ran again, the
model phrased every page slug differently — `getting-started-introduction` where the
previous run had said `introduction` — and because a page is matched by
`(section_slug, slug)`, **all twenty-one pages were orphaned and re-proposed under new
addresses**. The site doubled in one pass, two of the orphans were written work, and
nothing failed.

Page identity was a free-text field a model filled in again on every run. It is derived
from the title now, and the merge falls back to matching by title, so both halves of
that are pinned here.
"""

from __future__ import annotations

import uuid

import pytest

from codelith.apps.documentation.services.site_service import SiteService
from codelith.knowledge.constants import PageStatus
from codelith.models.organization import Organization
from codelith.models.project import Project


@pytest.fixture
async def project(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-si-{tag}")
    db_session.add(org)
    await db_session.flush()
    p = Project(org_id=org.id, name="si", slug=f"si-{tag}")
    db_session.add(p)
    await db_session.flush()
    return p


def _map(pages: list[tuple[str, str]], *, section="getting-started") -> dict:
    """`pages` is `(title, slug)` — the slug being what a model proposed."""
    return {
        "title": "Documentation",
        "sections": [
            {
                "slug": section,
                "title": "Getting Started",
                "order_index": 0,
                "pages": [
                    {
                        "slug": slug,
                        "title": title,
                        "doc_type": "getting_started",
                        "intent": f"about {title}",
                        "key_files": [],
                        "confidence": 0.9,
                        "reason": "",
                        "order_index": i,
                    }
                    for i, (title, slug) in enumerate(pages)
                ],
            }
        ],
    }


async def _merge(db, project_id: int, raw: dict):
    """
    The production path: analysis coerces its proposal, then merges it.

    `site_planner.py` does exactly these two in this order, and going straight to the
    merge would skip the half of the fix that lives in the coercion.
    """
    from codelith.knowledge.sites import coerce_site_map

    site_map = coerce_site_map(
        raw, known_files=set(), fallback_title="Documentation",
        max_sections=10, max_pages=50,
    )
    return await SiteService(db).merge_proposal(project_id, site_map)


async def _live(db, site_id):
    from codelith.db.repositories.site_repo import DocPageRepository

    rows = await DocPageRepository(db).list_for_site(site_id)
    return {f"{p.section_slug}/{p.slug}": p for p in rows}


class TestASecondAnalysisRecognisesItsOwnPages:
    @pytest.mark.asyncio
    async def test_a_rephrased_slug_does_not_orphan_the_page(
        self, db_session, project
    ) -> None:
        """
        The exact observed failure. Same page, same title, a slug the model wrote
        differently the second time.
        """
        first = await _merge(db_session, project.id, _map([("SDK Overview", "introduction")]))
        assert first.inserted == 1

        second = await _merge(db_session, project.id, _map([("SDK Overview", "getting-started-introduction")])
        )

        assert second.orphaned == 0, "a rephrased slug is not a deleted page"
        assert second.inserted == 0, "and not a new one either"
        pages = await _live(db_session, first.site_id)
        assert len(pages) == 1

    @pytest.mark.asyncio
    async def test_written_work_survives_it(self, db_session, project) -> None:
        """
        The part that made this expensive rather than untidy: two of the orphaned
        pages had prose in them, and the replacements were empty.
        """
        counts = await _merge(db_session, project.id, _map([("SDK Overview", "introduction")]))
        pages = await _live(db_session, counts.site_id)
        page = pages["getting-started/sdk-overview"]
        page.content_markdown = "Real prose somebody read."
        page.status = PageStatus.READY
        await db_session.flush()

        await _merge(db_session, project.id, _map([("SDK Overview", "something-else-entirely")])
        )

        after = await _live(db_session, counts.site_id)
        assert len(after) == 1
        survivor = next(iter(after.values()))
        assert survivor.content_markdown == "Real prose somebody read."
        assert survivor.status == PageStatus.READY

    @pytest.mark.asyncio
    async def test_the_address_does_not_move(self, db_session, project) -> None:
        """
        A recognised page keeps its own slug. The address is a URL somebody may have
        bookmarked and other pages may have linked to, so recognising a page must
        never relocate it.
        """
        counts = await _merge(db_session, project.id, _map([("SDK Overview", "introduction")]))
        before = set(await _live(db_session, counts.site_id))

        await _merge(db_session, project.id, _map([("SDK Overview", "renamed-by-the-model")]))

        assert set(await _live(db_session, counts.site_id)) == before

    @pytest.mark.asyncio
    async def test_the_slug_no_longer_repeats_its_section(
        self, db_session, project
    ) -> None:
        """
        `getting-started/getting-started-introduction` says it twice, and the run that
        produced slugs like that is the one that orphaned the site.
        """
        from codelith.knowledge.sites import coerce_site_map

        site_map = coerce_site_map(
            _map([("Introduction", "getting-started-introduction")]),
            known_files=set(),
            fallback_title="Documentation",
            max_sections=10,
            max_pages=50,
        )
        slug = site_map["sections"][0]["pages"][0]["slug"]

        assert slug == "introduction"

    @pytest.mark.asyncio
    async def test_a_genuinely_dropped_page_is_still_orphaned(
        self, db_session, project
    ) -> None:
        """
        The behaviour that must survive the fix. Matching more loosely would be worth
        nothing if it also stopped retiring pages analysis no longer proposes.
        """
        counts = await _merge(db_session, project.id, _map([("SDK Overview", "a"), ("Installing It", "b")])
        )
        assert counts.inserted == 2

        second = await _merge(db_session, project.id, _map([("SDK Overview", "a")]))

        assert second.orphaned == 1
        pages = await _live(db_session, counts.site_id)
        assert pages["getting-started/installing-it"].status == PageStatus.ORPHANED

    @pytest.mark.asyncio
    async def test_merging_the_same_map_twice_changes_nothing(
        self, db_session, project
    ) -> None:
        """
        Idempotence, which the merge already promised. Restated because title matching
        is a second way for a proposal to find a row, and a second way to find a row is
        a second way to touch one that did not change.
        """
        proposal = _map([("SDK Overview", "introduction"), ("Installing It", "install")])
        await _merge(db_session, project.id, proposal)

        again = await _merge(db_session, project.id, proposal)

        assert (again.inserted, again.updated, again.orphaned) == (0, 0, 0)


class TestWhichRowAProposalIsMatchedTo:
    @pytest.mark.asyncio
    async def test_a_live_page_beats_an_orphan_of_the_same_name(
        self, db_session, project
    ) -> None:
        """
        A section can hold two rows with one title — an orphan from an earlier naming
        and the page that replaced it — which is precisely the state the original bug
        leaves behind. The live one is the one to recognise.
        """
        counts = await _merge(db_session, project.id, _map([("SDK Overview", "old")]))
        # Drop it, then propose it again under a third slug: an orphan and a live row
        # now share a title.
        await _merge(db_session, project.id, _map([("Something Else", "other")]))
        await _merge(db_session, project.id, _map([("SDK Overview", "new")]))

        pages = await _live(db_session, counts.site_id)
        revived = [p for p in pages.values() if p.title == "SDK Overview"]
        live = [p for p in revived if p.status != PageStatus.ORPHANED]

        assert len(live) == 1, "one live page for one proposed page"
