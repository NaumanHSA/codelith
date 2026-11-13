"""
Each reading keeps its files: code and project files, each distinct content stored
once, a real `.env` with its values masked before it reaches the database. The code
viewer shows a kept file whole, and the map draws the project files in *Build & run*.
"""

from __future__ import annotations

import uuid
import zlib
from pathlib import Path

import pytest_asyncio
from sqlalchemy import func, select

from codelith.agents.analysis import StructuredExtractorAgent
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.db.repositories.knowledge.source_repo import SnapshotFile
from codelith.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from codelith.knowledge.atlas import AtlasService
from codelith.knowledge.constants import KBStatus
from codelith.models.graph import GraphFile
from codelith.models.job import Job
from codelith.models.knowledge import KBEntity, KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.source import ReadingFile, SourceBlob

CODE = {
    "app/main.py": "from app.store import save\n\n\ndef run():\n    return save()\n",
    "app/store.py": "def save():\n    return 1\n",
}
PROJECT = {
    "pyproject.toml": '[project]\nname = "shop"\ndependencies = ["fastapi>=0.110"]\n',
    ".env": "DATABASE_URL=postgres://admin:hunter2@db/shop\nDEBUG=\n",
    ".env.example": "DATABASE_URL=postgres://user:pass@localhost/shop\n",
    "Dockerfile": "FROM python:3.12-slim\nCOPY . /app\n",
    ".github/workflows/ci.yml": "on: push\njobs: {}\n",
    "README.md": "# Shop\n\nRun `make dev`.\n",
    "tests/fixtures/pyproject.toml": "[project]\nname = 'fixture'\n",
}


@pytest_asyncio.fixture
async def job(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-rf-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-rf-{tag}")
    db_session.add(project)
    await db_session.flush()
    job = Job(project_id=project.id, job_type="analysis", status="running", config_json={})
    db_session.add(job)
    await db_session.flush()
    job.project = project
    return job


def _checkout(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _state(job, root: Path, commit: str, code: dict[str, str]) -> dict:
    codebase = ParsedCodebase(root_path=str(root))
    codebase.files = [ParsedFile(path=p, language="python", content=c, size_bytes=len(c)) for p, c in code.items()]
    codebase.languages = {"python": len(code)}
    return {
        "project": job.project,
        "job": job,
        "codebase": codebase,
        "repo_path": str(root),
        "ingestion_result": {"commit_sha": commit},
        "api_specs": [],
        "infra_context": [],
    }


async def _read(db_session, job, root: Path, commit: str, code: dict[str, str] = CODE) -> int:
    result = await StructuredExtractorAgent(db=db_session, job_id=job.id).run(_state(job, root, commit, code))
    return result["kb_id"]


class TestAReadingKeepsItsFiles:
    async def test_code_and_project_files_are_kept_with_their_kinds(self, db_session, job, tmp_path) -> None:
        _checkout(tmp_path, {**CODE, **PROJECT})
        kb_id = await _read(db_session, job, tmp_path, "c1" * 20)
        kept = {f.path: f for f in await KnowledgeRepositories.for_session(db_session).sources.files(kb_id)}

        assert set(kept) == set(CODE) | (set(PROJECT) - {"tests/fixtures/pyproject.toml"})
        assert kept["app/main.py"].kind is None
        assert {p: kept[p].kind for p in PROJECT if p in kept} == {
            "pyproject.toml": "manifest",
            ".env": "env",
            ".env.example": "env",
            "Dockerfile": "deploy",
            ".github/workflows/ci.yml": "ci",
            "README.md": "docs",
        }
        assert kept["Dockerfile"].language == "dockerfile"

    async def test_a_real_env_never_reaches_the_database(self, db_session, job, tmp_path) -> None:
        _checkout(tmp_path, {**CODE, **PROJECT})
        kb_id = await _read(db_session, job, tmp_path, "c2" * 20)
        sources = KnowledgeRepositories.for_session(db_session).sources
        env = await sources.content(kb_id, ".env")
        assert env is not None and "DATABASE_URL=" in env and "hunter2" not in env
        assert (await sources.entry(kb_id, ".env")).masked
        for (data,) in (await db_session.execute(select(SourceBlob.data))).all():
            assert b"hunter2" not in zlib.decompress(data)

    async def test_project_files_are_fingerprinted_like_code(self, db_session, job, tmp_path) -> None:
        _checkout(tmp_path, {**CODE, **PROJECT})
        kb_id = await _read(db_session, job, tmp_path, "c3" * 20)
        kb = await KnowledgeRepositories.for_session(db_session).bases.get_by_id(kb_id)
        assert {"pyproject.toml", "Dockerfile", ".env"} <= set(kb.file_hashes_json)

    async def test_reading_the_same_commit_again_keeps_one_list(self, db_session, job, tmp_path) -> None:
        _checkout(tmp_path, {**CODE, **PROJECT})
        first = await _read(db_session, job, tmp_path, "c4" * 20)
        blobs = (await db_session.execute(select(func.count()).select_from(SourceBlob))).scalar_one()
        second = await _read(db_session, job, tmp_path, "c4" * 20)
        assert first == second
        rows = (await db_session.execute(select(func.count()).where(ReadingFile.kb_id == first))).scalar_one()
        assert rows == len(CODE) + len(PROJECT) - 1
        assert (await db_session.execute(select(func.count()).select_from(SourceBlob))).scalar_one() == blobs

    async def test_a_new_reading_stores_only_what_changed(self, db_session, job, tmp_path) -> None:
        _checkout(tmp_path, {**CODE, **PROJECT})
        await _read(db_session, job, tmp_path, "c5" * 20)
        before = (await db_session.execute(select(func.count()).select_from(SourceBlob))).scalar_one()

        changed = {**CODE, "app/store.py": "def save():\n    return 2\n"}
        _checkout(tmp_path, changed)
        kb_id = await _read(db_session, job, tmp_path, "c6" * 20, changed)
        after = (await db_session.execute(select(func.count()).select_from(SourceBlob))).scalar_one()
        assert after == before + 1
        assert await KnowledgeRepositories.for_session(db_session).sources.content(kb_id, "app/store.py") == changed[
            "app/store.py"
        ]


class TestTheContentIsStoredOnce:
    async def test_two_readings_share_their_blobs_and_sweep_keeps_them(self, db_session, job) -> None:
        sources = KnowledgeRepositories.for_session(db_session).sources
        a = KnowledgeBase(project_id=job.project_id, commit_sha="a" * 40, status=KBStatus.READY)
        b = KnowledgeBase(project_id=job.project_id, commit_sha="b" * 40, status=KBStatus.READY)
        db_session.add_all([a, b])
        await db_session.flush()
        shared = SnapshotFile(path="x.py", content="same = True\n", language="python")
        first = await sources.store(a.id, [shared])
        second = await sources.store(b.id, [shared, SnapshotFile(path="y.py", content="other\n")])
        assert (first.new_blobs, second.new_blobs) == (1, 1)
        assert await sources.manifest(a.id) == {"x.py": (await sources.manifest(b.id))["x.py"]}
        await sources.sweep()
        assert await sources.content(a.id, "x.py") == "same = True\n"


class TestTheMapAndTheViewer:
    @pytest_asyncio.fixture
    async def kb(self, db_session, job, tmp_path):
        _checkout(tmp_path, {**CODE, **PROJECT})
        kb_id = await _read(db_session, job, tmp_path, "c7" * 20)
        key = {"project_id": job.project_id, "kb_id": kb_id}
        # What the graph builder writes: the parsed code, and the kept project files.
        for path in CODE:
            db_session.add(GraphFile(**key, path=path, module_key=path[:-3].replace("/", "."), language="python", loc=4))
        for kept in await KnowledgeRepositories.for_session(db_session).sources.files(kb_id, project_only=True):
            db_session.add(GraphFile(**key, path=kept.path, module_key=None, language=kept.language, loc=kept.lines))
        await db_session.flush()
        return await KnowledgeRepositories.for_session(db_session).bases.get_by_id(kb_id)

    async def test_project_files_are_drawn_in_build_and_run(self, db_session, kb) -> None:
        atlas = await AtlasService(db_session, kb).build()
        nodes = {n.path: n for n in atlas.nodes}
        assert nodes["pyproject.toml"].kind == "manifest"
        assert nodes[".github/workflows/ci.yml"].kind == "ci"
        part = atlas.components[nodes["Dockerfile"].component]
        assert (part.name, part.group) == ("Build & run", "setup")

    async def test_a_config_file_is_one_node_not_a_file_and_a_fact(self, db_session, kb) -> None:
        declared = (
            await db_session.execute(select(KBEntity.name).where(KBEntity.kb_id == kb.id, KBEntity.kind == "config_file"))
        ).scalars().all()
        assert "pyproject.toml" in declared
        atlas = await AtlasService(db_session, kb).build()
        assert [n.path for n in atlas.nodes].count("pyproject.toml") == 1
        assert not any(n.fact == "config_file" and n.source == "pyproject.toml" for n in atlas.nodes)

    async def test_the_viewer_shows_a_kept_file_whole(self, db_session, job, kb, monkeypatch) -> None:
        from codelith.services.code_service import CodeService

        service = CodeService(db_session)

        async def anyone(*_args, **_kwargs):
            return None

        monkeypatch.setattr(service.projects, "get", anyone)
        monkeypatch.setattr(service.bases, "get_latest_usable", lambda _pid: _async(kb))

        dockerfile = await service.file(job.project_id, "Dockerfile", user=None)
        assert dockerfile.whole and dockerfile.indexed and dockerfile.lines_missing == 0
        assert dockerfile.segments[0].text == PROJECT["Dockerfile"].rstrip("\n")
        env = await service.file(job.project_id, ".env", user=None)
        assert env.masked and "hunter2" not in env.segments[0].text

        tree = await service.tree(job.project_id, user=None)
        listed = {f.path: f for f in tree.files}
        assert listed["README.md"].has_source and listed["app/main.py"].has_source


async def _async(value):
    return value
