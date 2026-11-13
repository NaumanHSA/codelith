"""
How to run it, from the files a reading keeps: each part from the file that says it,
the commands people type ahead of what a manifest implies, and the environment the
code reads compared with what any file declares.
"""

from __future__ import annotations

import textwrap
import uuid

import pytest_asyncio

from codelith.db.repositories.knowledge.source_repo import SnapshotFile, SourceRepository
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.detectors import project_file_kind, project_file_language
from codelith.knowledge.runbook import RunbookService, ci_commands, env_template, make_targets
from codelith.models.knowledge import KBEntity, KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project

FILES = {
    "pyproject.toml": textwrap.dedent(
        """
        [project]
        name = "shop"
        requires-python = ">=3.11"
        dependencies = ["fastapi>=0.110"]

        [project.optional-dependencies]
        dev = ["pytest>=8"]

        [project.scripts]
        shop = "shop.cli:main"
        """
    ),
    "Makefile": textwrap.dedent(
        """
        .PHONY: install dev test
        VERSION := 1.0

        install: ## Install everything
        \tpip install -e ".[dev]"

        # Run the API with reload
        dev:
        \tuvicorn shop.main:app --reload

        test: ## Run the tests
        \tpytest -q
        """
    ),
    "docker-compose.yml": textwrap.dedent(
        """
        services:
          app:
            build: .
            environment:
              - DATABASE_URL=postgres://shop@db/shop
          db:
            image: postgres:16
        """
    ),
    "Dockerfile": "FROM python:3.12-slim\nENV PORT=8000 \\\n    WORKERS=2\nEXPOSE 8000\n",
    ".env.example": "# Where the data lives\nDATABASE_URL=\nDEBUG=false\nSECRET_KEY=\n",
    ".github/workflows/ci.yml": textwrap.dedent(
        """
        jobs:
          test:
            steps:
              - run: |
                  pip install -e ".[dev]"
                  make test
              - run: echo done
        """
    ),
    "ui/package.json": '{"engines": {"node": ">=20"}, "scripts": {"dev": "vite", "build": "vite build", "test": "vitest"}}',
    "ui/pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
}


@pytest_asyncio.fixture
async def project(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-rb-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-rb-{tag}")
    db_session.add(project)
    await db_session.flush()
    return project


async def _reading(db_session, project, files: dict[str, str], env: list[tuple[str, str, dict]] = ()) -> KnowledgeBase:
    kb = KnowledgeBase(project_id=project.id, commit_sha=uuid.uuid4().hex, status=KBStatus.READY)
    db_session.add(kb)
    await db_session.flush()
    await SourceRepository(db_session).store(
        kb.id,
        [
            SnapshotFile(path=p, content=c, language=project_file_language(p), kind=project_file_kind(p))
            for p, c in files.items()
        ]
        + [SnapshotFile(path="app/main.py", content="print(1)\n", language="python")],
    )
    for name, source, data in env:
        db_session.add(KBEntity(kb_id=kb.id, kind="env_var", name=name, source_path=source, data_json=data))
    await db_session.flush()
    return kb


class TestHowToRunIt:
    @pytest_asyncio.fixture
    async def book(self, db_session, project):
        kb = await _reading(
            db_session,
            project,
            FILES,
            env=[
                ("DATABASE_URL", "shop/config.py", {"required": True}),
                ("OPENAI_API_KEY", "shop/llm.py", {"required": True}),
                ("LOG_LEVEL", "shop/config.py", {"required": False}),
                ("PORT", "shop/main.py", {}),
            ],
        )
        return await RunbookService(db_session, kb).build()

    async def test_what_it_needs_comes_from_the_file_that_says_it(self, book) -> None:
        needs = {(n.what, n.version, n.source) for n in book.needs}
        assert ("Python", ">=3.11", "pyproject.toml") in needs
        assert ("Node.js", ">=20", "ui/package.json") in needs
        assert ("PostgreSQL", "16", "docker-compose.yml") in needs

    async def test_the_targets_people_type_come_before_what_a_manifest_implies(self, book) -> None:
        assert [s.command for s in book.install][:3] == ["make install", 'pip install -e ".[dev]"', "cd ui && pnpm install"]
        assert book.install[0].note == "Install everything"
        assert book.run[0].command == "make dev" and book.run[0].note == "Run the API with reload"
        assert "cd ui && pnpm dev" in [s.command for s in book.run]
        assert [s.command for s in book.test][:2] == ["make test", "pytest"]
        assert "cd ui && pnpm test" in [s.command for s in book.test]

    async def test_a_compose_file_is_how_to_run_it_in_a_container(self, book) -> None:
        commands = [s.command for s in book.container]
        assert commands == ["docker compose up", "docker compose up --build"]

    async def test_ci_says_what_is_really_run(self, book) -> None:
        assert [s.command for s in book.ci] == ['pip install -e ".[dev]"', "make test"]

    async def test_the_environment_the_code_reads_is_compared_with_what_files_declare(self, book) -> None:
        env = {e.name: e for e in book.env}
        assert book.env[0].name == "OPENAI_API_KEY" and env["OPENAI_API_KEY"].missing
        assert env["OPENAI_API_KEY"].secret
        # Read and in no template, but the code has a default: worth knowing, not a blocker.
        assert env["LOG_LEVEL"].undocumented and not env["LOG_LEVEL"].missing
        assert set(env["DATABASE_URL"].declared_in) == {".env.example", "docker-compose.yml"}
        # The compose file gives it a value; the template gives SECRET_KEY none.
        assert env["DATABASE_URL"].has_default and env["DEBUG"].has_default
        assert not env["SECRET_KEY"].has_default and env["SECRET_KEY"].secret
        assert env["PORT"].declared_in == ["Dockerfile"] and not env["PORT"].missing
        assert env["PORT"].has_default  # the image sets it

    async def test_it_reads_as_markdown(self, book) -> None:
        text = book.markdown()
        assert "**Needs:** Python >=3.11 (`pyproject.toml`)" in text
        assert "- `make test`: Run the tests (`Makefile`)" in text
        assert "Needed by the code and declared nowhere: `OPENAI_API_KEY`" in text
        assert "Read by the code, in no template (1): `LOG_LEVEL`" in text


async def test_a_dockerfile_alone_is_built_and_run(db_session, project) -> None:
    kb = await _reading(db_session, project, {"Dockerfile": "FROM node:20\nEXPOSE 3000\n"})
    book = await RunbookService(db_session, kb).build()
    assert [s.command for s in book.container] == ["docker build -t app . && docker run --rm -p 3000:3000 app"]


async def test_a_reading_without_files_says_so(db_session, project) -> None:
    kb = KnowledgeBase(project_id=project.id, commit_sha="old" * 10, status=KBStatus.READY)
    db_session.add(kb)
    await db_session.flush()
    book = await RunbookService(db_session, kb).build()
    assert not book.available and "Read the codebase again" in book.reason


def test_a_comment_block_above_a_target_is_not_its_description() -> None:
    text = "# Long story about the build.\n# It goes on.\nbuild:\n\tgo build\n# Short.\nrun:\n\tgo run .\n"
    assert make_targets(text) == [("build", ""), ("run", "Short.")]


def test_container_targets_go_with_the_container_and_variants_follow(db_session) -> None:
    from codelith.knowledge.runbook import Runbook, RunbookService

    book = Runbook()
    RunbookService._targets(
        book,
        "Makefile",
        "",
        [(f"make {t}", t, "") for t in ("docker-down", "test-unit", "docker", "test", "dev")],
    )
    for steps in (book.test, book.container, book.run):
        steps.sort(key=lambda s: s.order)
    assert [s.command for s in book.test] == ["make test", "make test-unit"]
    assert [s.command for s in book.container] == ["make docker"]
    assert [s.command for s in book.run] == ["make dev"]


def test_make_targets_skip_variables_and_specials() -> None:
    assert make_targets(FILES["Makefile"]) == [
        ("install", "Install everything"),
        ("dev", "Run the API with reload"),
        ("test", "Run the tests"),
    ]


def test_an_env_template_says_which_have_values() -> None:
    assert env_template("A=1\nB=\n# C=3\nexport D='x'\n") == {"A": True, "B": False, "D": True}


def test_ci_commands_keep_install_build_and_test() -> None:
    assert ci_commands("steps:\n  - run: npm ci\n  - run: echo hi\n  - script: [go test ./...]\n") == ["npm ci", "go test ./..."]
