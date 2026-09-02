"""
Page-based composition, end to end with the LLM stubbed.

What is being verified is the change of *level*: the same retrieve-then-write
machinery now operates on a page and its headings rather than on a document and its
sections, and the page it wrote is recorded with enough provenance to be audited and,
in S5, invalidated by a commit.

The legacy doc-type path is exercised alongside it in every test that could plausibly
break it — the whole phasing depends on that path continuing to work untouched.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.agents.analysis import StructuredExtractorAgent
from codelith.apps.documentation.agents import (
    CompositionPlannerAgent,
    CompositionWriterAgent,
    KBLoaderAgent,
)
from codelith.apps.documentation.agents.publisher import PublisherAgent
from codelith.apps.documentation.services.site_service import SiteService
from codelith.core.exceptions import ValidationError
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from codelith.knowledge.constants import KBStatus, NarrativeTopic, PageStatus
from codelith.models.chunk import CodeChunk
from codelith.models.job import Job
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.user import User

ROUTES = textwrap.dedent(
    '''
    router = APIRouter()

    @router.get("/widgets/{widget_id}")
    async def get_widget(widget_id: int):
        """Return one widget."""
        return {}
    '''
)
SERVICE = textwrap.dedent(
    '''
    class WidgetService:
        """Widget business logic."""
        async def create(self, data: dict) -> dict:
            return data
    '''
)


def page(slug: str, title: str, order: int = 0, **kw) -> dict:
    return {
        "slug": slug,
        "title": title,
        "doc_type": "api",
        "intent": f"Covers {title}.",
        "key_files": ["app/api/routes.py"],
        "confidence": 0.9,
        "reason": "1 route detected",
        "order_index": order,
        **kw,
    }


SITE_MAP = {
    "title": "widgets",
    "sections": [
        {
            "slug": "api",
            "title": "API Reference",
            "order_index": 0,
            "pages": [
                page("endpoints", "Endpoints"),
                page("schemas", "Schemas", 1),
                # No anchor files: the evidence gate must skip this one when a whole
                # section is requested, and honour it when it is named outright.
                page("errors", "Errors", 2, key_files=[]),
            ],
        }
    ],
}


@pytest_asyncio.fixture
async def kb(db_session: AsyncSession) -> dict:
    """A knowledge base with a merged site map, ready to compose pages from."""
    tag = uuid4().hex[:8]
    org = Organization(name="Acme", slug=f"acme-{tag}")
    db_session.add(org)
    await db_session.flush()

    project = Project(org_id=org.id, name="widgets", slug=f"widgets-{tag}")
    db_session.add(project)
    await db_session.flush()

    job = Job(project_id=project.id, job_type="composition", status="running", config_json={})
    db_session.add(job)
    await db_session.flush()
    job.project = project

    codebase = ParsedCodebase(root_path="/tmp/repo")
    codebase.files = [
        ParsedFile(path="app/api/routes.py", language="python",
                   content=ROUTES, size_bytes=len(ROUTES)),
        ParsedFile(path="app/services/widget.py", language="python",
                   content=SERVICE, size_bytes=len(SERVICE)),
    ]
    extracted = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(
        {"project": project, "job": job, "codebase": codebase,
         "ingestion_result": {"commit_sha": f"sha-{tag}"}}
    )
    kb_id = extracted["kb_id"]

    repos = KnowledgeRepositories.for_session(db_session)
    await repos.modules.set_summary(kb_id, "app/api", "Exposes widget HTTP routes.")
    await repos.narratives.upsert(kb_id, NarrativeTopic.OVERVIEW, "A widget service.")
    db_session.add(
        CodeChunk(project_id=project.id, kb_id=kb_id, source_path="app/api/routes.py",
                  language="python", chunk_type="code", content=ROUTES,
                  start_line=1, end_line=8)
    )
    await repos.bases.finish_build(kb_id, status=KBStatus.READY, stats={"modules": 2})

    await SiteService(db_session).merge_proposal(project.id, SITE_MAP, kb_id=kb_id)
    await db_session.commit()

    return {
        "kb_id": kb_id, "project": project, "job": job, "commit_sha": f"sha-{tag}",
    }


@pytest.fixture
def sites(db_session: AsyncSession) -> SiteService:
    return SiteService(db_session)


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, kb: dict) -> User:
    """A member of the project's org — the read path authorises before it reads."""
    member = User(
        org_id=kb["project"].org_id,
        email=f"reader-{uuid4().hex[:8]}@example.com",
        password_hash="x",
        role="user",
    )
    db_session.add(member)
    await db_session.flush()
    return member


class TestScope:
    async def test_a_page_address_selects_one_page(self, kb, sites) -> None:
        pages = await sites.resolve_scope(kb["project"].id, ["api/endpoints"])
        assert [p.slug for p in pages] == ["endpoints"]

    async def test_a_section_selects_its_evidenced_pages(self, kb, sites) -> None:
        """A page with no anchor files would be written from narratives alone."""
        pages = await sites.resolve_scope(kb["project"].id, ["api"])
        assert [p.slug for p in pages] == ["endpoints", "schemas"]

    async def test_naming_a_page_outright_bypasses_the_evidence_gate(
        self, kb, sites
    ) -> None:
        """The user asked for it; the gate is for "give me the whole section"."""
        pages = await sites.resolve_scope(kb["project"].id, ["api/errors"])
        assert [p.slug for p in pages] == ["errors"]

    async def test_a_page_is_never_written_twice_in_one_job(self, kb, sites) -> None:
        pages = await sites.resolve_scope(kb["project"].id, ["api", "api/endpoints"])
        assert [p.slug for p in pages] == ["endpoints", "schemas"]

    async def test_a_section_skips_pages_that_are_already_written(
        self, kb, sites
    ) -> None:
        """Asking for a section is asking for the gaps in it — the S4 workflow."""
        site = await sites.sites.get_for_project(kb["project"].id)
        written = await sites.pages.get_by_slug(site.id, "api", "endpoints")
        written.status = PageStatus.READY
        written.content_markdown = "# Endpoints"
        await sites.db.flush()

        pages = await sites.resolve_scope(kb["project"].id, ["api"])

        assert [p.slug for p in pages] == ["schemas"]

    async def test_naming_a_written_page_regenerates_it(self, kb, sites) -> None:
        site = await sites.sites.get_for_project(kb["project"].id)
        written = await sites.pages.get_by_slug(site.id, "api", "endpoints")
        written.status = PageStatus.READY
        await sites.db.flush()

        pages = await sites.resolve_scope(kb["project"].id, ["api/endpoints"])

        assert [p.slug for p in pages] == ["endpoints"]

    async def test_a_fully_written_section_is_rejected_not_silently_empty(
        self, kb, sites
    ) -> None:
        site = await sites.sites.get_for_project(kb["project"].id)
        for page_ in await sites.pages.list_for_site(site.id):
            page_.status = PageStatus.READY
        await sites.db.flush()

        with pytest.raises(ValidationError, match="already written"):
            await sites.resolve_scope(kb["project"].id, ["api"])

    async def test_an_unknown_address_is_rejected(self, kb, sites) -> None:
        with pytest.raises(ValidationError, match="api/invented"):
            await sites.resolve_scope(kb["project"].id, ["api/invented"])

    async def test_the_per_job_cap_is_enforced(self, kb, sites) -> None:
        """A 30-page site in one job is an hour; that has to be deliberate."""
        with pytest.raises(ValidationError, match="per-job limit"):
            await sites.resolve_scope(kb["project"].id, ["api"], max_pages=1)


class TestKBLoader:
    async def test_it_resolves_pages_and_claims_them(self, db_session, kb, sites) -> None:
        job = kb["job"]
        result = await KBLoaderAgent(db=db_session, job_id=job.id).run(
            {
                "project": kb["project"],
                "job": job,
                "job_config": {"kb_id": kb["kb_id"], "page_slugs": ["api/endpoints"]},
            }
        )

        assert [p["address"] for p in result["pages"]] == ["api/endpoints"]
        assert result["pages"][0]["key_files"] == ["app/api/routes.py"]
        assert result["commit_sha"] == kb["commit_sha"]

        claimed = await sites.pages.get_by_slug(
            (await sites.sites.get_for_project(kb["project"].id)).id, "api", "endpoints"
        )
        assert claimed.status == PageStatus.GENERATING

    async def test_it_loads_the_whole_nav_not_just_the_scope(self, db_session, kb) -> None:
        """Every page prompt carries it, or pages repeat each other."""
        result = await KBLoaderAgent(db=db_session, job_id=kb["job"].id).run(
            {
                "project": kb["project"],
                "job": kb["job"],
                "job_config": {"kb_id": kb["kb_id"], "page_slugs": ["api/endpoints"]},
            }
        )

        slugs = [p["slug"] for p in result["site_map"]["sections"][0]["pages"]]
        assert slugs == ["endpoints", "schemas", "errors"]

    async def test_no_page_scope_is_the_legacy_path(self, db_session, kb) -> None:
        result = await KBLoaderAgent(db=db_session, job_id=kb["job"].id).run(
            {
                "project": kb["project"],
                "job": kb["job"],
                "job_config": {"kb_id": kb["kb_id"], "doc_types": ["architecture"]},
            }
        )

        assert result["pages"] == []
        assert result["doc_types"] == ["architecture"]


class TestPagePlanning:
    async def test_the_planner_plans_headings_inside_one_page(
        self, db_session, kb, monkeypatch
    ) -> None:
        async def fake_json(self, messages, task_type="plan", **kwargs):
            # The site map must have reached the prompt, or the model cannot be told
            # what its neighbours already own.
            assert "api/schemas" in messages[1]["content"]
            return {
                "sections": [
                    {"name": "Listing widgets", "focus": "GET routes",
                     "key_files": ["app/api/routes.py"]},
                    {"name": "Invented", "focus": "x", "key_files": ["nope.py"]},
                ]
            }

        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm_json", fake_json)
        state = await self._loaded(db_session, kb, ["api/endpoints"])

        result = await CompositionPlannerAgent(db=db_session, job_id=kb["job"].id).run(state)

        plan = result["documentation_plan"]["api/endpoints"]
        assert plan["page_id"] == state["pages"][0]["id"]
        assert [s["name"] for s in plan["sections"]] == ["Listing widgets", "Invented"]
        # A hallucinated anchor is dropped, exactly as in doc-type mode.
        assert plan["sections"][1]["key_files"] == []

    async def test_a_failed_plan_still_writes_the_page(
        self, db_session, kb, monkeypatch
    ) -> None:
        """One well-grounded heading beats five invented ones."""
        async def fake_json(self, messages, task_type="plan", **kwargs):
            return None

        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm_json", fake_json)
        state = await self._loaded(db_session, kb, ["api/endpoints"])

        result = await CompositionPlannerAgent(db=db_session, job_id=kb["job"].id).run(state)

        sections = result["documentation_plan"]["api/endpoints"]["sections"]
        assert [s["name"] for s in sections] == ["Endpoints"]
        assert sections[0]["key_files"] == ["app/api/routes.py"]

    @staticmethod
    async def _loaded(db_session, kb, page_slugs) -> dict:
        state = {
            "project": kb["project"],
            "job": kb["job"],
            "job_config": {"kb_id": kb["kb_id"], "page_slugs": page_slugs},
        }
        return state | await KBLoaderAgent(db=db_session, job_id=kb["job"].id).run(state)


class TestPageWriting:
    async def test_a_page_is_written_and_published_with_provenance(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        state = await self._written(db_session, kb, monkeypatch)

        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)

        site = await sites.sites.get_for_project(kb["project"].id)
        written = await sites.pages.get_by_slug(site.id, "api", "endpoints")
        assert written.status == PageStatus.READY
        assert "get_widget" in (written.content_markdown or "")
        assert written.word_count > 0
        assert written.job_id == kb["job"].id
        assert written.kb_id == kb["kb_id"]
        assert written.commit_sha == kb["commit_sha"]
        assert written.source_files_json == ["app/api/routes.py"]

    async def test_the_writer_tells_a_page_what_its_neighbours_cover(
        self, db_session, kb, monkeypatch
    ) -> None:
        """Cross-page duplication cannot be spotted from inside one page."""
        seen: list[str] = []

        async def capture(self, messages, task_type="write", **kwargs):
            seen.append(messages[1]["content"])
            return "Prose."

        state = await self._planned(db_session, kb, monkeypatch)
        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm", capture)
        await CompositionWriterAgent(db=db_session, job_id=kb["job"].id).run(state)

        assert any("Schemas" in prompt and "Errors" in prompt for prompt in seen)

    async def test_a_page_that_produced_nothing_is_marked_failed(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        """Better than leaving it `generating` in a spinner forever."""
        state = await self._planned(db_session, kb, monkeypatch)

        async def empty(self, messages, task_type="write", **kwargs):
            return ""

        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm", empty)
        written = await CompositionWriterAgent(db=db_session, job_id=kb["job"].id).run(state)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state | written)

        site = await sites.sites.get_for_project(kb["project"].id)
        page = await sites.pages.get_by_slug(site.id, "api", "endpoints")
        assert page.status == PageStatus.FAILED

    async def test_a_page_the_writer_never_reached_does_not_stay_generating(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        """A crashed fan-out branch must not leave the nav lying."""
        state = await self._planned(db_session, kb, monkeypatch, ["api"])

        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(
            state | {"generated_docs": []}
        )

        site = await sites.sites.get_for_project(kb["project"].id)
        statuses = {
            p.slug: p.status for p in await sites.pages.list_for_site(site.id)
        }
        assert statuses["endpoints"] == PageStatus.FAILED
        assert statuses["schemas"] == PageStatus.FAILED

    async def test_the_legacy_document_path_is_untouched(
        self, db_session, kb, monkeypatch
    ) -> None:
        """Nothing may break while the page path is being proven."""
        async def fake_json(self, messages, task_type="plan", **kwargs):
            return {"title": "Widgets Architecture", "sections": [
                {"name": "Overview", "focus": "the shape",
                 "key_files": ["app/api/routes.py"]}
            ]}

        async def fake_write(self, messages, task_type="write", **kwargs):
            return "Prose about the architecture."

        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm_json", fake_json)
        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm", fake_write)

        state = {
            "project": kb["project"],
            "job": kb["job"],
            "job_config": {"kb_id": kb["kb_id"], "doc_types": ["architecture"]},
        }
        state |= await KBLoaderAgent(db=db_session, job_id=kb["job"].id).run(state)
        state |= await CompositionPlannerAgent(db=db_session, job_id=kb["job"].id).run(state)
        state |= await CompositionWriterAgent(db=db_session, job_id=kb["job"].id).run(state)
        result = await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)

        assert result["saved_doc_ids"]
        assert result.get("saved_page_ids", []) == []

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    async def _planned(db_session, kb, monkeypatch, scope=None) -> dict:
        async def fake_json(self, messages, task_type="plan", **kwargs):
            return {"sections": [
                {"name": "Listing widgets", "focus": "GET routes",
                 "key_files": ["app/api/routes.py"]}
            ]}

        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm_json", fake_json)
        state = {
            "project": kb["project"],
            "job": kb["job"],
            "job_config": {"kb_id": kb["kb_id"], "page_slugs": scope or ["api/endpoints"]},
        }
        state |= await KBLoaderAgent(db=db_session, job_id=kb["job"].id).run(state)
        state |= await CompositionPlannerAgent(db=db_session, job_id=kb["job"].id).run(state)
        return state

    async def _written(self, db_session, kb, monkeypatch) -> dict:
        state = await self._planned(db_session, kb, monkeypatch)

        async def fake_write(self, messages, task_type="write", **kwargs):
            return "The `get_widget` handler returns one widget."

        monkeypatch.setattr("codelith.agents.base.BaseAgent._call_llm", fake_write)
        return state | await CompositionWriterAgent(db=db_session, job_id=kb["job"].id).run(state)


class TestIncrementalGrowth:
    """
    The workflow the whole design is for: add a section to a site that already has
    one, and leave everything already written alone.
    """

    async def test_adding_a_section_leaves_the_first_untouched(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)

        site = await sites.sites.get_for_project(kb["project"].id)
        first = await sites.pages.get_by_slug(site.id, "api", "endpoints")
        before = (first.content_markdown, first.updated_at, first.job_id)

        # A later analysis proposes a whole new section. Nothing already written may
        # be re-run, renamed or reverted.
        grown = {
            "title": "widgets",
            "sections": [
                *SITE_MAP["sections"],
                {
                    "slug": "architecture",
                    "title": "Architecture",
                    "order_index": 1,
                    "pages": [page("overview", "How it fits together",
                                   doc_type="architecture")],
                },
            ],
        }
        counts = await sites.merge_proposal(kb["project"].id, grown, kb_id=kb["kb_id"])

        assert (counts.inserted, counts.orphaned) == (1, 0)
        assert (first.content_markdown, first.updated_at, first.job_id) == before

        # And composing the new section does not pick the written page back up.
        scoped = await sites.resolve_scope(kb["project"].id, ["architecture"])
        assert [p.slug for p in scoped] == ["overview"]

    async def test_the_job_records_what_it_was_asked_to_do(
        self, db_session, kb, sites
    ) -> None:
        """"wrote API Reference · 2 pages", not "composition completed"."""
        pages = await sites.resolve_scope(kb["project"].id, ["api"])

        scope = await sites.describe_scope(kb["project"].id, pages)

        assert scope["kind"] == "pages"
        assert scope["sections"] == ["api"]
        assert scope["labels"] == ["API Reference"]
        assert scope["pages"] == ["api/endpoints", "api/schemas"]


class TestNavAwareHome:
    async def test_home_comes_from_the_map_and_the_overview_narrative(
        self, db_session, kb, sites, user
    ) -> None:
        """
        Derived on every read, so it cannot fall behind the nav — there is no
        stored copy to go stale.
        """
        out = await sites.get_site(kb["project"].id, user)
        assert out.home_markdown == "A widget service."

    async def test_home_survives_the_nav_changing(
        self, db_session, kb, sites, user
    ) -> None:
        await sites.merge_proposal(
            kb["project"].id,
            {"title": "widgets", "sections": [
                {"slug": "guides", "title": "Guides", "order_index": 0,
                 "pages": [page("setup", "Setup")]},
            ]},
            kb_id=kb["kb_id"],
        )

        out = await sites.get_site(kb["project"].id, user)

        assert out.home_markdown == "A widget service."
        assert [s.slug for s in out.sections] == ["guides"]


class TestStaleness:
    """
    The differentiator: on a new commit, mark *exactly* the pages the change
    invalidated.

    "4 pages are out of date" with a one-click refresh of exactly those is a
    different product from "your docs might be old", which is what every
    documentation generator already offers and nobody acts on.
    """

    @staticmethod
    async def _rebuild(db_session, kb, *, changed: dict[str, str]) -> object:
        """A second knowledge base for the same project at a new commit."""
        from codelith.models.knowledge import KnowledgeBase

        repos = KnowledgeRepositories.for_session(db_session)
        old = await repos.bases.get_by_id(kb["kb_id"])
        new = KnowledgeBase(
            project_id=kb["project"].id,
            commit_sha="sha-next",
            status=KBStatus.READY,
            file_hashes_json={**(old.file_hashes_json or {}), **changed},
        )
        db_session.add(new)
        await db_session.flush()
        return new

    async def _write(self, db_session, kb, sites, monkeypatch):
        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)
        site = await sites.sites.get_for_project(kb["project"].id)
        return await sites.pages.get_by_slug(site.id, "api", "endpoints")

    async def test_a_page_whose_source_changed_goes_stale(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        written = await self._write(db_session, kb, sites, monkeypatch)
        assert written.source_files_json == ["app/api/routes.py"]

        new_kb = await self._rebuild(
            db_session, kb, changed={"app/api/routes.py": "different"}
        )
        report = await sites.mark_stale(kb["project"].id, new_kb)

        assert report["stale"] == ["api/endpoints"]
        assert written.status == PageStatus.STALE

    async def test_a_commit_that_touched_other_files_leaves_it_alone(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        """This is the precision the whole feature is for."""
        written = await self._write(db_session, kb, sites, monkeypatch)

        new_kb = await self._rebuild(
            db_session, kb, changed={"app/services/widget.py": "different"}
        )
        report = await sites.mark_stale(kb["project"].id, new_kb)

        assert report["stale"] == []
        assert report["unchanged"] == ["api/endpoints"]
        assert written.status == PageStatus.READY

    async def test_a_deleted_source_file_makes_the_page_stale(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        from codelith.models.knowledge import KnowledgeBase

        written = await self._write(db_session, kb, sites, monkeypatch)
        new_kb = KnowledgeBase(
            project_id=kb["project"].id,
            commit_sha="sha-next",
            status=KBStatus.READY,
            file_hashes_json={"app/services/widget.py": "same"},
        )
        db_session.add(new_kb)
        await db_session.flush()

        report = await sites.mark_stale(kb["project"].id, new_kb)

        assert report["stale"] == ["api/endpoints"]
        assert written.status == PageStatus.STALE

    async def test_planned_pages_are_never_stale(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        await self._write(db_session, kb, sites, monkeypatch)
        new_kb = await self._rebuild(
            db_session, kb, changed={"app/api/routes.py": "different"}
        )

        report = await sites.mark_stale(kb["project"].id, new_kb)

        assert report["stale"] == ["api/endpoints"]  # and not schemas or errors

    async def test_a_build_without_digests_marks_nothing(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        """
        Saying nothing beats marking the whole site stale on the strength of a
        missing column — which is what an older knowledge base has.
        """
        written = await self._write(db_session, kb, sites, monkeypatch)
        new_kb = await self._rebuild(db_session, kb, changed={})
        new_kb.file_hashes_json = {}
        await db_session.flush()

        report = await sites.mark_stale(kb["project"].id, new_kb)

        assert report == {"stale": [], "unchanged": []}
        assert written.status == PageStatus.READY


class TestRegeneration:
    async def test_a_rewrite_keeps_what_the_page_used_to_say(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        """Reviewing a diff is a different activity from reading a fresh blob."""
        site = await sites.sites.get_for_project(kb["project"].id)
        page_id = (await sites.pages.get_by_slug(site.id, "api", "endpoints")).id

        await sites.publish_page(
            page_id, content_markdown="First draft.", job_id=1,
            kb_id=kb["kb_id"], commit_sha="a", source_files=["app/api/routes.py"],
        )
        rewritten = await sites.publish_page(
            page_id, content_markdown="Second draft.", job_id=2,
            kb_id=kb["kb_id"], commit_sha="b", source_files=["app/api/routes.py"],
        )

        assert rewritten.content_markdown == "Second draft."
        assert rewritten.previous_markdown == "First draft."

    async def test_an_identical_rewrite_does_not_overwrite_the_history(
        self, db_session, kb, sites
    ) -> None:
        site = await sites.sites.get_for_project(kb["project"].id)
        page_id = (await sites.pages.get_by_slug(site.id, "api", "endpoints")).id

        for text in ("First.", "Second.", "Second."):
            page_row = await sites.publish_page(
                page_id, content_markdown=text, job_id=1, kb_id=kb["kb_id"],
                commit_sha="a", source_files=[],
            )

        assert page_row.previous_markdown == "First."

    async def test_qa_lands_on_the_page_it_reviewed(
        self, db_session, kb, sites, monkeypatch
    ) -> None:
        """One score for a twenty-page document was decorative."""
        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        state |= {
            "review_results": [
                {"address": "api/endpoints", "review": {"score": 8, "approved": True,
                                                        "issues": ["one nit"]}}
            ],
            "validation_results": [
                {"address": "api/endpoints", "claims_checked": 5, "claims_passed": 4}
            ],
        }

        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)

        site = await sites.sites.get_for_project(kb["project"].id)
        written = await sites.pages.get_by_slug(site.id, "api", "endpoints")
        assert written.qa_score == 8
        assert written.qa_json["claims_passed"] == 4
        assert written.qa_json["issues"] == ["one nit"]


class TestVersions:
    """
    A version's pages are ordinary `doc_pages` rows carrying its id, so a reader and
    an export walk the same code either way. What must hold is the isolation: the
    live set keeps changing, and a snapshot must not follow it.
    """

    async def _written_site(self, db_session, kb, sites, monkeypatch):
        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)
        return await sites.sites.get_for_project(kb["project"].id)

    async def test_a_snapshot_copies_the_written_pages(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        await self._written_site(db_session, kb, sites, monkeypatch)

        version = await sites.create_version(kb["project"].id, "v1.0", user)

        assert version.label == "v1.0"
        assert version.page_count == 1  # only `endpoints` was written
        assert version.commit_sha == kb["commit_sha"]

    async def test_a_snapshot_does_not_follow_the_live_site(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        """The entire point of a version."""
        site = await self._written_site(db_session, kb, sites, monkeypatch)
        await sites.create_version(kb["project"].id, "v1.0", user)

        live = await sites.pages.get_by_slug(site.id, "api", "endpoints")
        await sites.publish_page(
            live.id, content_markdown="Rewritten entirely.", job_id=kb["job"].id,
            kb_id=kb["kb_id"], commit_sha="later", source_files=[],
        )

        frozen = await sites.get_page(kb["project"].id, "api", "endpoints", user, "v1.0")
        current = await sites.get_page(kb["project"].id, "api", "endpoints", user)

        assert "get_widget" in (frozen.content_markdown or "")
        assert current.content_markdown == "Rewritten entirely."

    async def test_planned_pages_are_not_snapshotted(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        """Nobody wants to read what a project *planned* to document last March."""
        await self._written_site(db_session, kb, sites, monkeypatch)
        await sites.create_version(kb["project"].id, "v1.0", user)

        out = await sites.get_site(kb["project"].id, user, "v1.0")

        assert [p.slug for s in out.sections for p in s.pages] == ["endpoints"]

    async def test_the_live_site_still_shows_everything(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        await self._written_site(db_session, kb, sites, monkeypatch)
        await sites.create_version(kb["project"].id, "v1.0", user)

        out = await sites.get_site(kb["project"].id, user)

        assert len([p for s in out.sections for p in s.pages]) == 3
        assert out.version is None
        assert [v.label for v in out.versions] == ["v1.0"]

    async def test_a_snapshot_never_goes_stale(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        from codelith.models.knowledge import KnowledgeBase

        site = await self._written_site(db_session, kb, sites, monkeypatch)
        await sites.create_version(kb["project"].id, "v1.0", user)

        new_kb = KnowledgeBase(
            project_id=kb["project"].id, commit_sha="sha-next",
            status=KBStatus.READY, file_hashes_json={"app/api/routes.py": "changed"},
        )
        db_session.add(new_kb)
        await db_session.flush()
        report = await sites.mark_stale(kb["project"].id, new_kb)

        assert report["stale"] == ["api/endpoints"]  # the live page, once
        frozen = await sites.pages.get_by_slug(
            site.id, "api", "endpoints",
            version_id=(await sites.versions.get_by_label(site.id, "v1.0")).id,
        )
        assert frozen.status == PageStatus.READY

    async def test_two_versions_cannot_share_a_label(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        await self._written_site(db_session, kb, sites, monkeypatch)
        await sites.create_version(kb["project"].id, "v1.0", user)

        with pytest.raises(ValidationError, match="already has a version"):
            await sites.create_version(kb["project"].id, "v1.0", user)

    async def test_an_unwritten_site_cannot_be_snapshotted(
        self, kb, sites, user
    ) -> None:
        with pytest.raises(ValidationError, match="nothing written"):
            await sites.create_version(kb["project"].id, "v0", user)

    async def test_an_unknown_version_label_404s(self, kb, sites, user) -> None:
        from codelith.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await sites.get_site(kb["project"].id, user, "nope")

    async def test_a_merge_never_touches_a_snapshot(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        """
        The merge reads the live set only. A snapshot appearing there would be
        orphaned by the next analysis that dropped its page.
        """
        site = await self._written_site(db_session, kb, sites, monkeypatch)
        version = await sites.create_version(kb["project"].id, "v1.0", user)

        await sites.merge_proposal(
            kb["project"].id,
            {"title": "widgets", "sections": [
                {"slug": "guides", "title": "Guides", "order_index": 0,
                 "pages": [page("setup", "Setup")]},
            ]},
            kb_id=kb["kb_id"],
        )

        frozen = await sites.pages.get_by_slug(
            site.id, "api", "endpoints", version_id=version.id
        )
        assert frozen.status == PageStatus.READY


class TestExport:
    async def test_the_export_tree_carries_only_written_pages(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)

        tree = await sites.export_tree(kb["project"].id, user)

        assert [p.address for p in tree.pages] == ["api/endpoints"]
        assert tree.home_markdown == "A widget service."
        assert tree.title == "widgets"

    async def test_every_format_produces_an_archive(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        import zipfile
        from io import BytesIO

        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)

        for fmt in ("markdown", "mkdocs", "docusaurus", "html"):
            data, filename, media = await sites.export(kb["project"].id, fmt, user)
            assert media == "application/zip"
            assert filename.endswith(".zip") and fmt.replace("markdown", "markdown") in filename
            assert zipfile.ZipFile(BytesIO(data)).namelist()

    async def test_a_version_can_be_exported(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)
        await sites.create_version(kb["project"].id, "v1.0", user)

        _, filename, _ = await sites.export(kb["project"].id, "html", user, "v1.0")

        assert "v1.0" in filename

    async def test_an_unwritten_site_cannot_be_exported(self, kb, sites, user) -> None:
        with pytest.raises(ValidationError, match="nothing written"):
            await sites.export(kb["project"].id, "mkdocs", user)

    async def test_an_unknown_format_is_rejected(
        self, db_session, kb, sites, user, monkeypatch
    ) -> None:
        state = await TestPageWriting()._written(db_session, kb, monkeypatch)
        await PublisherAgent(db=db_session, job_id=kb["job"].id).run(state)

        with pytest.raises(ValidationError, match="Unknown export format"):
            await sites.export(kb["project"].id, "pdf", user)


class TestFanOut:
    def test_the_graph_sends_one_writer_per_page(self, kb) -> None:
        from codelith.apps.documentation.workflows.composition_workflow import CompositionWorkflow

        workflow = CompositionWorkflow(project=kb["project"], job=kb["job"], db=None)
        sends = workflow._fan_out_writers(
            {"pages": [{"address": "api/endpoints"}, {"address": "api/schemas"}]}
        )

        assert [s.arg["current_page"]["address"] for s in sends] == [
            "api/endpoints", "api/schemas"
        ]

    def test_without_pages_it_still_sends_one_writer_per_doc_type(self, kb) -> None:
        from codelith.apps.documentation.workflows.composition_workflow import CompositionWorkflow

        workflow = CompositionWorkflow(project=kb["project"], job=kb["job"], db=None)
        sends = workflow._fan_out_writers({"doc_types": ["architecture", "api"]})

        assert [s.arg["current_doc_type"] for s in sends] == ["architecture", "api"]
