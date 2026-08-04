"""
Composition agents against a real Postgres, with LLM calls stubbed.

The point of these is the *plumbing* of retrieve-then-write: that a section's context
is assembled from the knowledge base before any generation happens, that it stays
within budget, and that composition never needs the repository on disk.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analysis import StructuredExtractorAgent
from app.agents.composition import (
    CompositionPlannerAgent,
    CompositionWriterAgent,
    KBLoaderAgent,
)
from app.db.repositories.knowledge import KnowledgeRepositories
from app.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from app.knowledge.constants import KBStatus, NarrativeTopic
from app.knowledge.retrieval import SectionContextBuilder
from app.models.chunk import CodeChunk
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
    class WidgetService:
        """Widget business logic."""
        async def create(self, data: dict) -> dict:
            return data
    '''
)


@pytest_asyncio.fixture
async def kb(db_session: AsyncSession):
    """A small but complete knowledge base: modules, facts, chunks, a narrative."""
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
    await repos.modules.set_summary(kb_id, "app/services", "Widget business logic.")
    await repos.narratives.upsert(kb_id, NarrativeTopic.OVERVIEW, "A widget service.")
    await repos.narratives.upsert(kb_id, NarrativeTopic.ARCHITECTURE, "Layered: api → service.")

    # Chunks stand in for the repository, which no longer exists at composition time.
    db_session.add_all([
        CodeChunk(project_id=project.id, kb_id=kb_id, source_path="app/api/routes.py",
                  language="python", chunk_type="code", content=ROUTES,
                  start_line=1, end_line=8),
        CodeChunk(project_id=project.id, kb_id=kb_id, source_path="app/services/widget.py",
                  language="python", chunk_type="code", content=SERVICE,
                  start_line=1, end_line=5),
    ])
    await repos.bases.finish_build(kb_id, status=KBStatus.READY, stats={"modules": 2})
    await db_session.commit()

    return {"kb_id": kb_id, "project": project, "job": job}


class TestSectionRetrieval:
    async def test_context_is_assembled_from_the_kb_not_the_filesystem(
        self, db_session, kb
    ) -> None:
        builder = SectionContextBuilder(db_session, kb["kb_id"], kb["project"].id)

        ctx = await builder.build(
            {"name": "Endpoints", "focus": "the HTTP surface",
             "key_files": ["app/api/routes.py"]},
            doc_type="api",
        )

        assert not ctx.is_thin
        assert any("routes.py" in b for b in ctx.source_blocks)
        assert any("Exposes widget HTTP routes" in s for s in ctx.module_summaries)
        rendered = ctx.render()
        assert "get_widget" in rendered           # real source reached the prompt
        assert "## Source for this section" in rendered

    async def test_narratives_are_chosen_by_doc_type(self, db_session, kb) -> None:
        builder = SectionContextBuilder(db_session, kb["kb_id"], kb["project"].id)

        arch = await builder.build({"name": "Overview", "key_files": []}, doc_type="architecture")

        assert any("architecture" in n for n in arch.narratives)

    async def test_context_respects_the_token_budget(self, db_session, kb) -> None:
        tiny = SectionContextBuilder(
            db_session, kb["kb_id"], kb["project"].id, token_budget=120
        )
        ctx = await tiny.build(
            {"name": "Endpoints", "key_files": ["app/api/routes.py"]}, doc_type="api"
        )
        assert ctx.tokens <= 120 or len(ctx.source_blocks) == 1  # never trims to nothing

    async def test_unknown_files_yield_a_thin_context(self, db_session, kb) -> None:
        """A hallucinated path must not silently look like real context."""
        builder = SectionContextBuilder(db_session, kb["kb_id"], kb["project"].id)
        ctx = await builder.build(
            {"name": "Ghost", "key_files": ["app/does/not/exist.py"]}, doc_type="api"
        )
        assert ctx.source_blocks == []


class TestKBLoader:
    async def test_resolves_the_latest_usable_kb(self, db_session, kb) -> None:
        result = await KBLoaderAgent(db=db_session, job_id=kb["job"].id).run(
            {"project": kb["project"], "job_config": {"doc_types": ["api"]}}
        )

        assert result["kb_id"] == kb["kb_id"]
        assert result["doc_types"] == ["api"]
        assert result["generated_docs"] == []

    async def test_refuses_when_no_knowledge_base_exists(self, db_session) -> None:
        tag = uuid4().hex[:8]
        org = Organization(name="Empty", slug=f"empty-{tag}")
        db_session.add(org)
        await db_session.flush()
        project = Project(org_id=org.id, name="empty", slug=f"empty-{tag}")
        db_session.add(project)
        await db_session.flush()
        job = Job(project_id=project.id, job_type="composition", status="running", config_json={})
        db_session.add(job)
        await db_session.flush()

        with pytest.raises(ValueError, match="no usable knowledge base"):
            await KBLoaderAgent(db=db_session, job_id=job.id).run(
                {"project": project, "job_config": {}}
            )


class TestPlanner:
    async def test_hallucinated_key_files_are_dropped(self, db_session, kb, monkeypatch) -> None:
        """
        A path the KB does not contain would retrieve nothing, so the section would be
        written from thin air. Validate them away instead.
        """
        async def fake_json(self, messages, task_type="plan", **kwargs):
            return {
                "title": "API Reference",
                "sections": [
                    {"name": "Endpoints", "focus": "routes",
                     "key_files": ["app/api/routes.py", "app/invented/file.py"]}
                ],
            }

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm_json", fake_json)

        result = await CompositionPlannerAgent(db=db_session, job_id=kb["job"].id).run(
            {"project": kb["project"], "kb_id": kb["kb_id"], "doc_types": ["api"]}
        )

        section = result["documentation_plan"]["api"]["sections"][0]
        assert section["key_files"] == ["app/api/routes.py"]

    @pytest.mark.parametrize("bad_title", ["api", "  ", "docs"])
    async def test_useless_titles_are_replaced(
        self, db_session, kb, monkeypatch, bad_title
    ) -> None:
        """A planner returning literally 'api' would become the document heading."""
        async def fake_json(self, messages, task_type="plan", **kwargs):
            return {"title": bad_title, "sections": [
                {"name": "Endpoints", "focus": "routes", "key_files": ["app/api/routes.py"]}]}

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm_json", fake_json)

        result = await CompositionPlannerAgent(db=db_session, job_id=kb["job"].id).run(
            {"project": kb["project"], "kb_id": kb["kb_id"], "doc_types": ["api"]}
        )
        assert result["documentation_plan"]["api"]["title"] == "widgets — Api"

    async def test_falls_back_to_real_files_when_the_model_fails(
        self, db_session, kb, monkeypatch
    ) -> None:
        async def no_json(self, messages, task_type="plan", **kwargs):
            return None

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm_json", no_json)

        result = await CompositionPlannerAgent(db=db_session, job_id=kb["job"].id).run(
            {"project": kb["project"], "kb_id": kb["kb_id"], "doc_types": ["api"]}
        )

        sections = result["documentation_plan"]["api"]["sections"]
        assert sections  # defaults kicked in
        # Fallback still points at files that exist, so retrieval keeps working.
        assert all(
            all(f in {"app/api/routes.py", "app/services/widget.py"} for f in s["key_files"])
            for s in sections
        )


class TestWriter:
    @staticmethod
    def _plan() -> dict:
        return {
            "api": {
                "title": "API Reference",
                "sections": [
                    {"name": "Endpoints", "focus": "routes", "key_files": ["app/api/routes.py"]},
                    {"name": "Services", "focus": "logic", "key_files": ["app/services/widget.py"]},
                ],
            }
        }

    async def test_writes_one_section_per_plan_entry(self, db_session, kb, monkeypatch) -> None:
        calls: list[str] = []

        async def fake_llm(self, messages, task_type="write", **kwargs):
            calls.append(messages[1]["content"])
            return "Prose grounded in the context."

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm", fake_llm)

        result = await CompositionWriterAgent(db=db_session, job_id=kb["job"].id).run(
            {"project": kb["project"], "kb_id": kb["kb_id"], "doc_types": ["api"],
             "current_doc_type": "api", "documentation_plan": self._plan()}
        )

        doc = result["generated_docs"][0]
        assert doc["doc_type"] == "api"
        assert "## Endpoints" in doc["content_markdown"]
        assert "## Services" in doc["content_markdown"]
        # One call per section — not a tool loop.
        assert len(calls) == 2
        # Real source reached the prompt.
        assert any("get_widget" in c for c in calls)

    async def test_need_context_triggers_exactly_one_retry(
        self, db_session, kb, monkeypatch
    ) -> None:
        """The escape hatch must be bounded — it is not an exploration loop."""
        attempts: list[int] = []

        async def always_asks(self, messages, task_type="write", **kwargs):
            attempts.append(1)
            return "NEED_CONTEXT: how does auth work"

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm", always_asks)

        result = await CompositionWriterAgent(db=db_session, job_id=kb["job"].id).run(
            {"project": kb["project"], "kb_id": kb["kb_id"], "doc_types": ["api"],
             "current_doc_type": "api",
             "documentation_plan": {"api": {"title": "T", "sections": [
                 {"name": "Endpoints", "focus": "routes", "key_files": ["app/api/routes.py"]}]}}}
        )

        # Exactly two attempts for the one section, then it gives up.
        assert len(attempts) == 2
        assert result["generated_docs"][0]["content_markdown"] == ""

    async def test_a_failing_section_does_not_lose_the_document(
        self, db_session, kb, monkeypatch
    ) -> None:
        seen: list[int] = []

        async def flaky(self, messages, task_type="write", **kwargs):
            seen.append(1)
            if len(seen) == 1:
                raise RuntimeError("model exploded")
            return "Second section survived."

        monkeypatch.setattr("app.agents.base.BaseAgent._call_llm", flaky)

        result = await CompositionWriterAgent(db=db_session, job_id=kb["job"].id).run(
            {"project": kb["project"], "kb_id": kb["kb_id"], "doc_types": ["api"],
             "current_doc_type": "api", "documentation_plan": self._plan()}
        )

        content = result["generated_docs"][0]["content_markdown"]
        assert "survived" in content


class TestGraphShape:
    def test_composition_state_reduces_only_generated_docs(self) -> None:
        from app.workflows.composition_states import CompositionState

        annotations = CompositionState.__annotations__
        assert "kb_id" in annotations
        assert "generated_docs" in annotations
        # Analysis inputs must not leak into composition.
        assert "codebase" not in annotations
        assert "repo_path" not in annotations

    def test_workflow_compiles_with_the_reused_back_half(self, kb) -> None:
        from app.workflows.composition_workflow import CompositionWorkflow

        graph = CompositionWorkflow(
            project=kb["project"], job=kb["job"], db=None
        )._build_graph()
        nodes = set(graph.get_graph().nodes)

        for expected in ("kb_loader", "strategy", "planner", "writer",
                         "diagram", "qa", "gate", "formatter", "publisher"):
            assert expected in nodes
