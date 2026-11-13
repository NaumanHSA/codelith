"""
The dependency audit on a reading's kept files, offline; and the online checks against
a stand-in for OSV.dev and PyPI, so nothing is sent anywhere by the tests.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest_asyncio
from sqlalchemy import select

from codelith.apps.qa.service import QAService, steps_for
from codelith.db.repositories.knowledge.source_repo import SnapshotFile, SourceRepository
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.detectors import project_file_kind, project_file_language
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.qa import QAFinding, QARun

FILES = {
    "pyproject.toml": (
        '[project]\nname = "shop"\nrequires-python = ">=3.9"\ndependencies = [\n'
        '    "fastapi>=0.110",\n    "jinja2==2.10",\n    "requests",\n]\n\n'
        '[project.optional-dependencies]\ndev = ["rich>=13"]\n'
    ),
    "app/main.py": "import yaml\nfrom fastapi import FastAPI\nimport jinja2\nfrom rich import print\n\nmatch 1:\n    case _:\n        pass\n",
    "tests/test_main.py": "from rich import print\n",
    "Dockerfile": "FROM python:3.8-slim\nUSER app\n",
}


@pytest_asyncio.fixture
async def kb(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-qd-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-qd-{tag}")
    db_session.add(project)
    await db_session.flush()
    kb = KnowledgeBase(project_id=project.id, commit_sha=uuid.uuid4().hex, status=KBStatus.READY)
    db_session.add(kb)
    await db_session.flush()
    await SourceRepository(db_session).store(
        kb.id,
        [
            SnapshotFile(
                path=p,
                content=c,
                language=project_file_language(p) if project_file_kind(p) else "python",
                kind=project_file_kind(p),
            )
            for p, c in FILES.items()
        ],
    )
    await db_session.commit()
    return kb


async def _run(db_session, kb, online=False, transport=None):
    run = QARun(project_id=kb.project_id, kb_id=kb.id, areas_json=["dependencies"], scope_json={"kind": "all"}, online=online)
    db_session.add(run)
    await db_session.commit()
    service = QAService(db_session)
    if transport is not None:
        # The online check takes its HTTP transport from the run's cache: a stand-in here.
        original = service._scope

        async def scoped(*a, **kw):
            return await original(*a, **kw)

        service._scope = scoped
        import codelith.apps.qa.context as context_module

        real = context_module.RunContext.__init__

        def init(self, *a, **kw):
            real(self, *a, **kw)
            self.cache["http_transport"] = transport

        context_module.RunContext.__init__ = init
        try:
            await service.execute(run.id)
        finally:
            context_module.RunContext.__init__ = real
    else:
        await service.execute(run.id)
    rows = list((await db_session.execute(select(QAFinding).where(QAFinding.run_id == run.id))).scalars())
    return run, rows


class TestOffline:
    async def test_what_the_audit_finds(self, db_session, kb) -> None:
        run, found = await _run(db_session, kb)
        rules = {(f.rule, f.title) for f in found}
        assert ("deps.undeclared", "`yaml` is imported but not declared in `pyproject.toml`") in rules
        assert ("deps.dev-at-runtime", "`rich` is declared for development only, and shipped code imports it") in rules
        assert ("deps.unused", "`requests` is declared and never imported") in rules
        assert ("deps.unpinned", "`requests` asks for no version, and nothing locks one") in rules
        assert any(f.rule == "compat.syntax" and "match" in f.title for f in found)
        assert any(f.rule == "compat.image" and f.title.startswith("The image runs Python 3.8") for f in found)
        assert "qa_online" not in [c["id"] for c in run.summary_json["checks"]]

    def test_the_online_step_only_when_allowed(self) -> None:
        assert "qa_online" not in steps_for(["dependencies"]) and "qa_online" in steps_for(["dependencies"], True)


class TestOnline:
    async def test_known_vulnerability_with_a_patch_and_a_note_of_what_was_sent(self, db_session, kb) -> None:
        seen: list[str] = []

        def answer(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/v1/querybatch":
                queries = json.loads(request.content)["queries"]
                return httpx.Response(
                    200, json={"results": [{"vulns": [{"id": "GHSA-test"}]} if q["package"]["name"] == "jinja2" else {} for q in queries]}
                )
            if request.url.path == "/v1/vulns/GHSA-test":
                return httpx.Response(
                    200,
                    json={
                        "id": "GHSA-test",
                        "aliases": ["CVE-2024-0001"],
                        "summary": "Sandbox escape",
                        "database_specific": {"severity": "HIGH"},
                        "affected": [{"package": {"name": "jinja2", "ecosystem": "PyPI"}, "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.11.3"}]}]}],
                    },
                )
            if request.url.host == "pypi.org":
                name = request.url.path.split("/")[2]
                return httpx.Response(200, json={"info": {"version": {"fastapi": "1.2.0"}.get(name, "3.1.4"), "license": "MIT"}})
            return httpx.Response(404)

        run, found = await _run(db_session, kb, online=True, transport=httpx.MockTransport(answer))
        vuln = next(f for f in found if f.rule == "deps.known-vulnerability")
        assert vuln.title == "`jinja2` 2.10 has 1 known vulnerability" and vuln.severity == "high"
        assert "CVE-2024-0001" in vuln.message and vuln.path == "pyproject.toml" and vuln.line == 6
        assert vuln.patch and '+    "jinja2>=2.11.3",' in vuln.patch
        assert any(f.rule == "deps.outdated" and f.title.startswith("`fastapi` is 1 major version behind") for f in found)
        notes = " ".join(run.summary_json["notes"])
        assert "Sent 1 package names and versions to OSV.dev" in notes and "PyPI" in notes
        # Only package names and versions went out: no paths, no code.
        assert all("app/" not in url and "main.py" not in url for url in seen)

    async def test_a_service_that_cannot_be_reached_is_said(self, db_session, kb) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no network")

        run, found = await _run(db_session, kb, online=True, transport=httpx.MockTransport(down))
        assert not any(f.rule == "deps.known-vulnerability" for f in found)
        assert any("OSV.dev could not be reached" in n for n in run.summary_json["notes"])
