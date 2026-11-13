"""
Reading a codebase again keeps what did not change.

Three readings of one small codebase, with the model and the embedder stubbed and
counted: the first reads everything; the second, after one service file changed,
embeds and summarises only that; the third, after only a test changed, makes no model
call at all for summaries or the architecture.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.agents.analysis import (
    ArchitectureSynthesizerAgent,
    ModuleSummarizerAgent,
    SemanticIndexerAgent,
    StructuredExtractorAgent,
)
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from codelith.knowledge.constants import KBStatus
from codelith.llm.providers import embedding_spec
from codelith.models.chunk import CodeChunk
from codelith.models.job import Job
from codelith.models.organization import Organization
from codelith.models.project import Project

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
TEST = "def test_a():\n    pass\n"


@pytest_asyncio.fixture
async def job(db_session: AsyncSession) -> Job:
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


def state_for(job: Job, commit: str, *, service: str = SERVICE, test: str = TEST, force: bool = False) -> dict:
    codebase = ParsedCodebase(root_path="/tmp/repo")
    codebase.files = [
        ParsedFile(path="app/api/routes.py", language="python", content=ROUTES, size_bytes=len(ROUTES)),
        ParsedFile(path="app/services/widget.py", language="python", content=service, size_bytes=len(service)),
        ParsedFile(path="tests/test_widget.py", language="python", content=test, size_bytes=len(test)),
    ]
    codebase.languages = {"python": 3}
    return {
        "project": job.project,
        "job": job,
        "codebase": codebase,
        "ingestion_result": {"commit_sha": commit},
        "api_specs": [],
        "infra_context": [],
        "force": force,
    }


class Counter:
    def __init__(self) -> None:
        self.embedded: list[int] = []
        self.summaries = 0
        self.architecture = 0


@pytest_asyncio.fixture
def counted(monkeypatch) -> Counter:
    seen = Counter()

    async def embed(texts, model=None, batch_size=None):
        seen.embedded.append(len(texts))
        return [[0.25] * 8 for _ in texts]

    async def summarise(self, messages, task_type=None, **_):
        seen.summaries += 1
        return "A summary."

    async def architecture(self, messages, task_type=None, **_):
        seen.architecture += 1
        return {"services": [{"name": "Widgets"}], "relations": []}

    monkeypatch.setattr("codelith.agents.analysis.semantic_indexer.create_embeddings", embed)
    monkeypatch.setattr(ModuleSummarizerAgent, "_call_llm", summarise)
    monkeypatch.setattr(ArchitectureSynthesizerAgent, "_call_llm_json", architecture)
    return seen


async def read(db: AsyncSession, job: Job, state: dict) -> dict:
    """The stages this test is about, then sealed the way the persister seals a reading."""
    out = dict(state)
    for agent in (StructuredExtractorAgent, SemanticIndexerAgent, ModuleSummarizerAgent, ArchitectureSynthesizerAgent):
        out.update(await agent(db=db, job_id=job.id).run(out))
    repos = KnowledgeRepositories.for_session(db)
    await repos.bases.finish_build(
        out["kb_id"],
        status=KBStatus.READY,
        stats={"embedding": {"model": embedding_spec().model, "dimensions": 8}},
        architecture=out.get("architecture_map") or {},
    )
    await db.commit()
    return out


async def chunk_count(db: AsyncSession, kb_id: int) -> int:
    result = await db.execute(select(func.count()).select_from(CodeChunk).where(CodeChunk.kb_id == kb_id))
    return result.scalar_one()


class TestIncrementalReading:
    async def test_a_changed_service_file_is_the_only_thing_redone(self, db_session, job, counted) -> None:
        first = await read(db_session, job, state_for(job, "c1"))
        assert not first["reuse"].get("from_kb")
        embedded_first = sum(counted.embedded)
        summaries_first = counted.summaries
        assert embedded_first > 0 and summaries_first > 0

        changed = SERVICE + "\n    async def delete(self, widget_id: int) -> None:\n        return None\n"
        second = await read(db_session, job, state_for(job, "c2", service=changed))
        reuse = second["reuse"]

        assert reuse["from_kb"] == first["kb_id"]
        assert reuse["changed"] == ["app/services/widget.py"]
        # Vectors: the unchanged files' chunks were copied, not embedded again.
        assert reuse["vectors_copied"] > 0
        assert sum(counted.embedded) - embedded_first == reuse["vectors_embedded"]
        # And the new reading holds every chunk, copied or fresh.
        assert await chunk_count(db_session, second["kb_id"]) == reuse["vectors_copied"] + reuse["vectors_embedded"]
        # Summaries: one module rewritten, the other kept.
        assert reuse["modules_rewritten"] == ["app/services"]
        assert reuse["summaries_kept"] >= 1
        assert counted.summaries - summaries_first == 1
        # A module changed, so the architecture was asked for again.
        assert reuse["structure_unchanged"] is False
        assert reuse["architecture_kept"] is False

        repos = KnowledgeRepositories.for_session(db_session)
        modules = {m.path: m for m in await repos.modules.list_by_kb(second["kb_id"], include_tests=True)}
        assert modules["app/api"].summary == "A summary."

    async def test_a_test_only_change_keeps_summaries_and_architecture(self, db_session, job, counted) -> None:
        await read(db_session, job, state_for(job, "c1"))
        summaries, architecture = counted.summaries, counted.architecture

        second = await read(db_session, job, state_for(job, "c2", test=TEST + "\ndef test_b():\n    pass\n"))
        reuse = second["reuse"]

        assert reuse["changed"] == ["tests/test_widget.py"]
        assert counted.summaries == summaries  # no summary call
        assert reuse["structure_unchanged"] is True
        assert reuse["architecture_kept"] is True
        assert counted.architecture == architecture  # no architecture call
        assert second["architecture_map"] == {"services": [{"name": "Widgets"}], "relations": []}

    async def test_force_reads_everything_again(self, db_session, job, counted) -> None:
        await read(db_session, job, state_for(job, "c1"))
        before = len(counted.embedded)

        second = await read(db_session, job, state_for(job, "c2", force=True))

        assert not second["reuse"].get("from_kb")
        assert len(counted.embedded) == before + 1  # one batch of everything
        assert second["reuse"].get("vectors_copied", 0) == 0


class TestNarratives:
    async def test_unchanged_topics_are_kept_and_not_written_again(self, db_session, job, counted, monkeypatch) -> None:
        from codelith.agents.analysis import NarrativeWriterAgent

        writes: list[str] = []
        proposals: list[int] = []

        async def write(self, messages, task_type="write", **_):
            writes.append(task_type)
            return "## Section\n\nGrounded prose."

        async def propose(self, *args, **kwargs):
            proposals.append(1)
            return []

        monkeypatch.setattr(NarrativeWriterAgent, "_call_llm", write)
        monkeypatch.setattr(NarrativeWriterAgent, "_propose_topics", propose)

        async def read_with_narratives(state: dict) -> dict:
            out = await read(db_session, job, state)
            out.update(await NarrativeWriterAgent(db=db_session, job_id=job.id).run(out))
            await db_session.commit()
            return out

        first = await read_with_narratives(state_for(job, "c1"))
        written_first, proposed_first = len(writes), len(proposals)
        assert written_first >= 2

        repos = KnowledgeRepositories.for_session(db_session)
        tests_module = {m.name for m in await repos.modules.list_by_kb(first["kb_id"], include_tests=True) if m.is_test}
        about_tests = {
            n.topic
            for n in await repos.narratives.list_by_kb(first["kb_id"])
            if tests_module & set((n.source_refs_json or {}).get("modules") or [])
        }

        second = await read_with_narratives(state_for(job, "c2", test=TEST + "\ndef test_b():\n    pass\n"))

        # Only a test changed. A narrative written from the tests module is written
        # again; every other one is kept, and the topic list stands without a
        # selection call.
        assert second["reuse"]["narratives_written"] == len(about_tests)
        assert second["reuse"]["narratives_kept"] == written_first - len(about_tests)
        assert second["reuse"]["narratives_kept"] >= 1
        assert len(writes) == written_first + len(about_tests)
        assert len(proposals) == proposed_first

        assert await repos.narratives.topics_present(second["kb_id"]) == await repos.narratives.topics_present(
            first["kb_id"]
        )
