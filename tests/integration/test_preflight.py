"""
The pre-flight, against a real graph.

The unit tests pin the judgement. This pins the part only a database answers: four
lookups against tables analysis filled, joined into one answer, including the join
that is easy to get subtly wrong — a *transitive* reach computed by a recursive CTE,
where the difference between correct and plausible is a file appearing at the wrong
distance or not at all.
"""

from __future__ import annotations

import uuid

import pytest

from codelith.knowledge.constants import KBStatus
from codelith.knowledge.preflight import PreflightService
from codelith.models.graph import GraphCall, GraphFile, GraphImport, GraphSymbol
from codelith.models.knowledge import KBEntity, KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.site import DocPage, DocSite


@pytest.fixture
async def kb(db_session):
    """A project with a knowledge base, and nothing in it yet."""
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-pf-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="pf", slug=f"pf-{tag}")
    db_session.add(project)
    await db_session.flush()
    base = KnowledgeBase(project_id=project.id, commit_sha=tag, status=KBStatus.READY)
    db_session.add(base)
    await db_session.flush()
    return base


async def _graph(db, kb, *, files: list[str], imports: list[tuple[str, str]] = ()) -> None:
    """`imports` is `(importer, imported)` — the direction the analyser records."""
    key = {"project_id": kb.project_id, "kb_id": kb.id}
    for path in files:
        db.add(GraphFile(**key, path=path, language="python"))
    for src, dst in imports:
        db.add(GraphImport(**key, src=src, dst=dst))
    await db.flush()


def _service(db, kb) -> PreflightService:
    return PreflightService(db, kb.id, kb.project_id)


class TestResolvingWhatTheCallerNamed:
    @pytest.mark.asyncio
    async def test_a_bare_filename_finds_the_one_file(self, db_session, kb) -> None:
        """
        Agents name files the way they see them. `client.py` has to reach
        `codelith/llm/client.py` or the tool is only usable by somebody who already
        knows the layout — which is the person who least needs it.
        """
        await _graph(db_session, kb, files=["codelith/llm/client.py", "codelith/main.py"])
        report = await _service(db_session, kb).inspect("client.py")
        assert report.files == ["codelith/llm/client.py"]
        assert report.kind == "file"

    @pytest.mark.asyncio
    async def test_an_ambiguous_name_resolves_to_nothing(self, db_session, kb) -> None:
        """
        Two `models.py` and no way to tell which was meant. Answering about the wrong
        one is worse than saying nothing — the caller acts on a confident answer.
        """
        await _graph(db_session, kb, files=["app/a/models.py", "app/b/models.py"])
        report = await _service(db_session, kb).inspect("models.py")
        assert report.found is False
        assert report.risk == "unknown"

    @pytest.mark.asyncio
    async def test_a_suffix_only_matches_on_a_path_boundary(self, db_session, kb) -> None:
        """`nt.py` must not match `client.py`."""
        await _graph(db_session, kb, files=["codelith/llm/client.py"])
        assert (await _service(db_session, kb).inspect("nt.py")).found is False

    @pytest.mark.asyncio
    async def test_a_symbol_resolves_to_where_it_is_defined(self, db_session, kb) -> None:
        await _graph(db_session, kb, files=["app/auth.py"])
        db_session.add(
            GraphSymbol(
                project_id=kb.project_id, kb_id=kb.id, path="app/auth.py",
                qname="Session.authenticate", name="authenticate", kind="method", line=42,
            )
        )
        await db_session.flush()

        report = await _service(db_session, kb).inspect("authenticate")
        assert report.kind == "symbol"
        assert report.files == ["app/auth.py"]
        assert "app/auth.py:42" in report.defined_at[0]

    @pytest.mark.asyncio
    async def test_a_file_wins_over_a_symbol_of_the_same_name(self, db_session, kb) -> None:
        """
        `main` is a plausible file and a plausible function. Both are tried and the
        file is preferred — a decision, rather than a guess made by looking for a dot
        in the string.
        """
        await _graph(db_session, kb, files=["app/main.py"])
        db_session.add(
            GraphSymbol(
                project_id=kb.project_id, kb_id=kb.id, path="app/cli.py",
                qname="main", name="main", kind="function", line=1,
            )
        )
        await db_session.flush()

        report = await _service(db_session, kb).inspect("main.py")
        assert report.kind == "file"
        assert report.files == ["app/main.py"]


class TestWhatWouldBreak:
    @pytest.mark.asyncio
    async def test_reach_is_transitive_with_distance(self, db_session, kb) -> None:
        """
        `b` imports `a`; `c` imports `b`. Changing `a` reaches `c` at two hops, which
        no single join answers and which is the whole reason the graph is here.
        """
        await _graph(
            db_session, kb,
            files=["a.py", "b.py", "c.py", "unrelated.py"],
            imports=[("b.py", "a.py"), ("c.py", "b.py")],
        )
        report = await _service(db_session, kb).inspect("a.py")

        assert report.dependents == ["b.py"]
        assert [(r.path, r.distance) for r in report.reached] == [("b.py", 1), ("c.py", 2)]
        assert "unrelated.py" not in {r.path for r in report.reached}

    @pytest.mark.asyncio
    async def test_a_file_is_not_its_own_dependent(self, db_session, kb) -> None:
        """
        A cycle is legal in most languages and common in practice. Reporting that
        changing `a.py` breaks `a.py` is true and useless.
        """
        await _graph(
            db_session, kb,
            files=["a.py", "b.py"],
            imports=[("b.py", "a.py"), ("a.py", "b.py")],
        )
        report = await _service(db_session, kb).inspect("a.py")
        assert "a.py" not in report.dependents
        assert "a.py" not in {r.path for r in report.reached}

    @pytest.mark.asyncio
    async def test_tests_are_separated_from_the_rest_of_the_reach(self, db_session, kb) -> None:
        """
        A test importing the file is reach *and* coverage. Counting it only as reach
        would make a well-tested module look more dangerous than an untested one.
        """
        await _graph(
            db_session, kb,
            files=["app/auth.py", "app/api.py", "tests/test_auth.py"],
            imports=[("app/api.py", "app/auth.py"), ("tests/test_auth.py", "app/auth.py")],
        )
        report = await _service(db_session, kb).inspect("app/auth.py")

        assert report.tests == ["tests/test_auth.py"]
        assert len(report.reached) == 2
        assert "1 test file(s) reach it" in report.headline()

    @pytest.mark.asyncio
    async def test_call_sites_are_reported_for_a_symbol(self, db_session, kb) -> None:
        await _graph(db_session, kb, files=["app/auth.py", "app/api.py"])
        db_session.add(
            GraphSymbol(
                project_id=kb.project_id, kb_id=kb.id, path="app/auth.py",
                qname="authenticate", name="authenticate", kind="function", line=10,
            )
        )
        db_session.add(
            GraphCall(
                project_id=kb.project_id, kb_id=kb.id,
                src_path="app/api.py", src_qname="login",
                dst_path="app/auth.py", dst_qname="authenticate",
            )
        )
        await db_session.flush()

        report = await _service(db_session, kb).inspect("authenticate")
        assert [(c.file, c.symbol) for c in report.callers] == [("app/api.py", "login")]
        assert "app/api.py :: login" in report.brief()


class TestWhatItMakesWrong:
    @pytest.mark.asyncio
    async def test_written_pages_citing_the_file_are_named(self, db_session, kb) -> None:
        site = DocSite(project_id=kb.project_id, title="Docs", nav_json=[])
        db_session.add(site)
        await db_session.flush()
        db_session.add(
            DocPage(
                site_id=site.id, section_slug="api", slug="auth", title="Authentication",
                doc_type="api", status="ready", order_index=0,
                content_markdown="Auth works like this.",
                source_files_json=["app/auth.py"],
            )
        )
        # A planned page cites nothing yet — telling an agent it will need re-writing
        # is a claim about the future.
        db_session.add(
            DocPage(
                site_id=site.id, section_slug="api", slug="planned", title="Planned",
                doc_type="api", status="planned", order_index=1,
                content_markdown=None, source_files_json=["app/auth.py"],
            )
        )
        await _graph(db_session, kb, files=["app/auth.py"])

        report = await _service(db_session, kb).inspect("app/auth.py")
        assert [p.address for p in report.documented_in] == ["api/auth"]
        assert "will need re-writing" in report.brief()

    @pytest.mark.asyncio
    async def test_facts_declared_in_the_file_are_surfaced(self, db_session, kb) -> None:
        """
        Renaming a handler is a local edit until you learn the file declares two HTTP
        routes. Facts from *another* file must not leak in.
        """
        await _graph(db_session, kb, files=["app/auth.py"])
        db_session.add(
            KBEntity(kb_id=kb.id, kind="route", name="POST /login",
                     source_path="app/auth.py", source_line=12)
        )
        db_session.add(
            KBEntity(kb_id=kb.id, kind="env_var", name="SESSION_TTL", source_path="app/auth.py")
        )
        db_session.add(
            KBEntity(kb_id=kb.id, kind="route", name="GET /health", source_path="app/other.py")
        )
        await db_session.flush()

        report = await _service(db_session, kb).inspect("app/auth.py")
        assert report.facts == ["env_var SESSION_TTL", "route POST /login (line 12)"]


class TestTheEndpoint:
    @pytest.mark.asyncio
    async def test_an_unresolved_target_is_an_answer_not_a_404(
        self, db_session, kb, client
    ) -> None:
        """
        "I have never seen that file" is a fact about the codebase. A 404 says the
        endpoint does not exist, and a caller cannot tell the two apart — one is a
        result to act on, the other a bug to report.
        """
        from codelith.core.security import create_access_token
        from codelith.models.user import User

        project = await db_session.get(Project, kb.project_id)
        user = User(
            org_id=project.org_id,
            email=f"pf-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="x",
            full_name="PF",
            role="manager",
            is_active=True,
        )
        db_session.add(user)
        await _graph(db_session, kb, files=["app/auth.py"])
        await db_session.flush()

        response = await client.get(
            f"/api/v1/projects/{kb.project_id}/preflight",
            params={"target": "nowhere/at/all.py"},
            headers={"Authorization": f"Bearer {create_access_token(str(user.id))}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["found"] is False
        assert body["risk"] == "unknown"
        assert "nowhere/at/all.py" in body["brief"]

    @pytest.mark.asyncio
    async def test_an_unanalysed_codebase_says_so(self, db_session, client) -> None:
        """A 409, not an empty report: there is nothing wrong with the request, and
        the caller's next move is to run an analysis rather than to try again."""
        from codelith.core.security import create_access_token
        from codelith.models.user import User

        tag = uuid.uuid4().hex[:8]
        org = Organization(name="o", slug=f"o-pf-{tag}")
        db_session.add(org)
        await db_session.flush()
        project = Project(org_id=org.id, name="unread", slug=f"unread-{tag}")
        user = User(
            org_id=org.id, email=f"pf-{tag}@example.com", password_hash="x",
            full_name="PF", role="manager", is_active=True,
        )
        db_session.add_all([project, user])
        await db_session.flush()

        response = await client.get(
            f"/api/v1/projects/{project.id}/preflight",
            params={"target": "anything.py"},
            headers={"Authorization": f"Bearer {create_access_token(str(user.id))}"},
        )
        assert response.status_code == 409
        assert "analysed" in response.json()["detail"]
