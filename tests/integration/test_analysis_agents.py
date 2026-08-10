"""
Analysis agents against a real Postgres.

LLM and embedding calls are stubbed: what is being verified here is that the
deterministic pipeline writes a correct, complete knowledge base and that the
READY/DEGRADED decision reflects what actually happened.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analysis import KBPersisterAgent, SemanticIndexerAgent, StructuredExtractorAgent
from app.db.repositories.knowledge import KnowledgeRepositories
from app.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from app.knowledge.constants import EntityKind, KBStatus, ModuleRole, PageStatus
from app.models.job import Job
from app.models.organization import Organization
from app.models.project import Project

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
    import os
    RETRIES = int(os.getenv("WIDGET_RETRIES", "3"))

    class WidgetService:
        """Widget business logic."""
        async def create(self, data: dict) -> dict:
            return data
    '''
)


@pytest_asyncio.fixture
async def job(db_session: AsyncSession) -> Job:
    # The agents under test call db.commit(), so fixture rows survive the session
    # rollback. Unique slugs per test keep runs independent.
    tag = uuid4().hex[:8]
    org = Organization(name="Acme", slug=f"acme-{tag}")
    db_session.add(org)
    await db_session.flush()

    project = Project(org_id=org.id, name="widgets", slug=f"widgets-{tag}")
    db_session.add(project)
    await db_session.flush()

    job = Job(project_id=project.id, job_type="analysis", status="running", config_json={})
    db_session.add(job)
    await db_session.flush()
    job.project = project
    return job


@pytest.fixture
def state(job: Job) -> dict:
    codebase = ParsedCodebase(root_path="/tmp/repo")
    codebase.files = [
        ParsedFile(path="app/api/routes.py", language="python",
                   content=ROUTES, size_bytes=len(ROUTES)),
        ParsedFile(path="app/services/widget.py", language="python",
                   content=SERVICE, size_bytes=len(SERVICE)),
        ParsedFile(path="tests/test_widget.py", language="python",
                   content="def test_a():\n    pass\n", size_bytes=30),
    ]
    codebase.languages = {"python": 3}
    return {
        "project": job.project,
        "job": job,
        "codebase": codebase,
        "ingestion_result": {"commit_sha": "deadbeef"},
        "api_specs": [],
        "infra_context": [],
    }


class TestStructuredExtractor:
    async def test_builds_a_knowledge_base_from_parsed_source(self, db_session, job, state) -> None:
        result = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)

        assert result["kb_id"] is not None
        assert result["commit_sha"] == "deadbeef"

        repos = KnowledgeRepositories.for_session(db_session)
        kb = await repos.bases.get_by_id(result["kb_id"])
        assert kb.status == KBStatus.RUNNING          # not sealed until kb_persister
        assert kb.commit_sha == "deadbeef"

    async def test_modules_are_persisted_with_roles(self, db_session, job, state) -> None:
        result = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)
        repos = KnowledgeRepositories.for_session(db_session)

        modules = {
            m.path: m
            for m in await repos.modules.list_by_kb(result["kb_id"], include_tests=True)
        }

        assert modules["app/api"].role == ModuleRole.API
        assert modules["app/services"].role == ModuleRole.SERVICE
        assert modules["tests"].is_test is True
        assert modules["app/services"].symbols_json  # symbols captured

    async def test_facts_are_persisted(self, db_session, job, state) -> None:
        result = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)
        repos = KnowledgeRepositories.for_session(db_session)

        routes = await repos.entities.list_by_kind(result["kb_id"], EntityKind.ROUTE)
        env = await repos.entities.list_by_kind(result["kb_id"], EntityKind.ENV_VAR)

        assert [r.name for r in routes] == ["GET /widgets/{widget_id}"]
        assert routes[0].data_json["handler"] == "get_widget"
        assert [e.name for e in env] == ["WIDGET_RETRIES"]

    async def test_rerunning_the_same_commit_does_not_duplicate(
        self, db_session, job, state
    ) -> None:
        first = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)
        second = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)

        assert first["kb_id"] == second["kb_id"]
        repos = KnowledgeRepositories.for_session(db_session)
        routes = await repos.entities.list_by_kind(second["kb_id"], EntityKind.ROUTE)
        assert len(routes) == 1  # cleared and rebuilt, not appended


class TestSemanticIndexer:
    async def test_embeds_in_batches_and_scopes_chunks_to_the_kb(
        self, db_session, job, state, monkeypatch
    ) -> None:
        extracted = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)
        calls: list[int] = []

        from app.config import get_settings

        dimensions = get_settings().VECTOR_DIMENSIONS

        async def fake_embeddings(texts, model=None, batch_size=None):
            calls.append(len(texts))
            # Follows the configured dimension: `code_chunks.embedding` is built
            # from VECTOR_DIMENSIONS, so a hardcoded width fails on any deployment
            # whose embedding model differs from whoever wrote the test.
            return [[0.1] * dimensions for _ in texts]

        monkeypatch.setattr(
            "app.agents.analysis.semantic_indexer.create_embeddings", fake_embeddings
        )

        result = await SemanticIndexerAgent(db=db_session, job_id=job.id).run(
            {**state, "kb_id": extracted["kb_id"]}
        )

        assert result["indexed_chunks"] > 0
        # One batched call, not one per chunk — the whole point of the change.
        assert len(calls) == 1

        from sqlalchemy import func, select

        from app.models.chunk import CodeChunk

        count = await db_session.execute(
            select(func.count()).select_from(CodeChunk).where(CodeChunk.kb_id == extracted["kb_id"])
        )
        assert count.scalar_one() == result["indexed_chunks"]

    async def test_failed_embeddings_are_dropped_not_stored_null(
        self, db_session, job, state, monkeypatch
    ) -> None:
        extracted = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)

        async def all_fail(texts, model=None, batch_size=None):
            return [None for _ in texts]

        monkeypatch.setattr("app.agents.analysis.semantic_indexer.create_embeddings", all_fail)

        result = await SemanticIndexerAgent(db=db_session, job_id=job.id).run(
            {**state, "kb_id": extracted["kb_id"]}
        )
        assert result["indexed_chunks"] == 0


class TestNarrativeWriter:
    async def test_concurrent_topics_all_succeed(
        self, db_session, job, state, monkeypatch
    ) -> None:
        """
        Regression: supporting facts must be read before the concurrent phase.

        Reading them inside the gather uses one AsyncSession from several tasks,
        which raises "another operation is in progress" and silently drops
        narratives — observed as 4 of 5 topics failing on a real run.
        """
        from app.agents.analysis import NarrativeWriterAgent

        extracted = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)

        async def fake_llm(self, messages, task_type="write", **kwargs):
            return "## Section\n\nGrounded prose."

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm", fake_llm)

        agent = NarrativeWriterAgent(db=db_session, job_id=job.id)
        result = await agent.run(
            {**state, "kb_id": extracted["kb_id"], "architecture_map": {"services": []}}
        )

        assert result["narrative_failures"] == 0
        assert result["narratives_written"] >= 2

        repos = KnowledgeRepositories.for_session(db_session)
        topics = await repos.narratives.topics_present(extracted["kb_id"])
        assert "overview" in topics and "architecture" in topics

    async def test_topics_are_chosen_from_evidence(
        self, db_session, job, state, monkeypatch
    ) -> None:
        """
        The floor stands whatever the selection call returns.

        A selector having a bad day must degrade quality, not silently drop a topic
        the extracted facts demand — so this stubs it out entirely and checks what
        survives.
        """
        from app.agents.analysis import NarrativeWriterAgent

        extracted = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)
        repos = KnowledgeRepositories.for_session(db_session)
        modules = await repos.modules.list_by_kb(extracted["kb_id"], include_tests=True)
        kinds = await repos.entities.kind_breakdown(extracted["kb_id"])

        async def no_proposals(self, *args, **kwargs):
            return []

        monkeypatch.setattr(
            "app.agents.analysis.narrative_writer.NarrativeWriterAgent._propose_topics",
            no_proposals,
        )

        agent = NarrativeWriterAgent(db=db_session, job_id=job.id)
        topics = {
            str(t)
            for t in await agent._choose_topics(job.project, {}, modules, kinds)
        }

        assert {"overview", "architecture"} <= topics       # always
        assert "request_lifecycle" in topics                # api + service modules exist
        assert "deployment" not in topics                   # no infra was found


class TestKBPersister:
    async def _seal(self, db_session, job, state, **overrides) -> dict:
        extracted = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)
        merged = {**state, **extracted, "indexed_chunks": 5, "narratives_written": 2, **overrides}
        # A narrative must exist for the "no narratives" degradation check to pass.
        if overrides.get("_with_narrative", True):
            repos = KnowledgeRepositories.for_session(db_session)
            await repos.narratives.upsert(extracted["kb_id"], "overview", "text")
        return await KBPersisterAgent(db=db_session, job_id=job.id).run(merged)

    async def test_healthy_build_is_ready_with_stats(self, db_session, job, state) -> None:
        result = await self._seal(db_session, job, state)

        assert result["kb_status"] == KBStatus.READY
        stats = result["kb_stats"]
        assert stats["modules"] == 3
        assert stats["languages"] == ["python"]
        assert stats["indexed_chunks"] == 5
        assert any(s["doc_type"] == "api" for s in stats["suggested_doc_types"])

    async def test_suggestions_reflect_what_was_found(self, db_session, job, state) -> None:
        result = await self._seal(db_session, job, state)
        suggestions = {s["doc_type"]: s for s in result["kb_stats"]["suggested_doc_types"]}

        assert "architecture" in suggestions
        assert "api" in suggestions  # a route was detected
        assert suggestions["api"]["reason"].startswith("1 HTTP route")

    async def test_fallback_architecture_marks_the_build_degraded(
        self, db_session, job, state
    ) -> None:
        result = await self._seal(db_session, job, state, architecture_degraded=True)

        assert result["kb_status"] == KBStatus.DEGRADED

        repos = KnowledgeRepositories.for_session(db_session)
        kb = await repos.bases.get_by_id(result["kb_id"])
        assert "deterministic fallback" in kb.error_message
        # Degraded is still usable — composition proceeds with a warning.
        assert kb.is_usable is True

    async def test_missing_embeddings_degrade_the_build(self, db_session, job, state) -> None:
        result = await self._seal(db_session, job, state, indexed_chunks=0)

        assert result["kb_status"] == KBStatus.DEGRADED
        repos = KnowledgeRepositories.for_session(db_session)
        kb = await repos.bases.get_by_id(result["kb_id"])
        assert "semantic retrieval unavailable" in kb.error_message


class TestSitePlanner:
    """
    The map analysis proposes, and the merge it drives.

    The LLM is stubbed, so what is verified is the part that must hold whatever the
    model says: `key_files` are real, slugs survive re-analysis, and a failed call
    still leaves a usable site.
    """

    @staticmethod
    def _proposal() -> dict:
        return {
            "title": "widgets",
            "sections": [
                {
                    "slug": "api",
                    "title": "API Reference",
                    "pages": [
                        {
                            "slug": "endpoints",
                            "title": "Endpoints",
                            "doc_type": "api",
                            "intent": "Every HTTP route and its shape.",
                            # One real path, one invented — only the real one may survive.
                            "key_files": ["app/api/routes.py", "app/api/invented.py"],
                            "confidence": 0.9,
                            "reason": "1 HTTP route detected",
                        }
                    ],
                }
            ],
        }

    async def _plan(self, db_session, job, state, monkeypatch, response) -> dict:
        from app.agents.analysis import SitePlannerAgent

        extracted = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state)

        async def fake_llm_json(self, messages, task_type="plan", **kwargs):
            return response

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm_json", fake_llm_json)
        return await SitePlannerAgent(db=db_session, job_id=job.id).run(
            {**state, "kb_id": extracted["kb_id"], "architecture_map": {"services": []}}
        )

    async def test_it_plans_a_site_and_merges_it(
        self, db_session, job, state, monkeypatch
    ) -> None:
        from app.features.documentation.services.site_service import SiteService

        result = await self._plan(db_session, job, state, monkeypatch, self._proposal())

        assert result["site_pages"] == 1
        assert result["site_degraded"] is False

        site = await SiteService(db_session).sites.get_with_pages(job.project_id)
        page = site.pages[0]
        assert (page.section_slug, page.slug) == ("api", "endpoints")
        assert page.status == PageStatus.PLANNED

    async def test_invented_key_files_are_discarded(
        self, db_session, job, state, monkeypatch
    ) -> None:
        """A path the KB has never seen retrieves nothing and must not be stored."""
        from app.features.documentation.services.site_service import SiteService

        await self._plan(db_session, job, state, monkeypatch, self._proposal())

        site = await SiteService(db_session).sites.get_with_pages(job.project_id)
        assert site.pages[0].key_files_json == ["app/api/routes.py"]

    async def test_the_proposal_is_stored_on_the_knowledge_base(
        self, db_session, job, state, monkeypatch
    ) -> None:
        result = await self._plan(db_session, job, state, monkeypatch, self._proposal())

        repos = KnowledgeRepositories.for_session(db_session)
        kb = await repos.bases.get_by_id(result["site_map"]["kb_id"])
        assert [s["slug"] for s in kb.site_map_json["sections"]] == ["api"]

    async def test_re_analysing_twice_changes_nothing(
        self, db_session, job, state, monkeypatch
    ) -> None:
        """The done-when for this phase, end to end."""
        from app.features.documentation.services.site_service import SiteService

        await self._plan(db_session, job, state, monkeypatch, self._proposal())
        site = await SiteService(db_session).sites.get_with_pages(job.project_id)
        before = {(p.section_slug, p.slug): p.id for p in site.pages}

        await self._plan(db_session, job, state, monkeypatch, self._proposal())

        site = await SiteService(db_session).sites.get_with_pages(job.project_id)
        after = {(p.section_slug, p.slug): p.id for p in site.pages}
        assert after == before

    async def test_a_failed_call_still_leaves_a_site(
        self, db_session, job, state, monkeypatch
    ) -> None:
        """A failed plan must cost site quality, not the site."""
        from app.features.documentation.services.site_service import SiteService

        result = await self._plan(db_session, job, state, monkeypatch, None)

        assert result["site_degraded"] is True
        assert result["site_pages"] > 0

        site = await SiteService(db_session).sites.get_with_pages(job.project_id)
        # Derived from the evidence-backed doc types, and still anchored on real files.
        assert {p.doc_type for p in site.pages} <= {"architecture", "api", "getting_started"}
        assert any(p.key_files_json for p in site.pages)

    async def test_the_fallback_degrades_the_knowledge_base(
        self, db_session, job, state, monkeypatch
    ) -> None:
        result = await self._plan(db_session, job, state, monkeypatch, None)
        sealed = await KBPersisterAgent(db=db_session, job_id=job.id).run(
            {**state, **result, "kb_id": result["site_map"]["kb_id"], "indexed_chunks": 5}
        )

        assert sealed["kb_status"] == KBStatus.DEGRADED


class TestGraphShape:
    def test_analysis_graph_has_no_doc_type_dependency(self) -> None:
        """Phase 1 must be composable-agnostic: the state has no doc_types key."""
        from app.workflows.analysis_states import AnalysisState

        assert "doc_types" not in AnalysisState.__annotations__
        assert "output_formats" not in AnalysisState.__annotations__
        assert "kb_id" in AnalysisState.__annotations__

    def test_workflow_compiles(self, job) -> None:
        from app.workflows.analysis_workflow import AnalysisWorkflow

        workflow = AnalysisWorkflow(project=job.project, job=job, db=None)
        graph = workflow._build_graph()
        nodes = set(graph.get_graph().nodes)

        for expected in (
            "repo_analyzer", "structured_extractor", "semantic_indexer",
            "module_summarizer", "architecture_synthesizer",
            "narrative_writer", "site_planner", "kb_persister",
        ):
            assert expected in nodes

    def test_the_ui_knows_every_analysis_stage(self) -> None:
        """
        A stage missing from `EXPECTED_STAGES` never appears in the progress bar and
        skews the denominator, so the job reports 6/6 and then keeps running.
        """
        from pathlib import Path

        narrate = Path("ui/src/app/lib/narrate.ts").read_text()
        assert "'site_planner_agent'" in narrate
