"""
The review gate, and coming back from it.

The gate existed for months as a decision nothing acted on: it routed to `END`, so a
held job simply stopped, and approving it set the row to `running` with no worker
attached — a job that reported *in progress* forever. Two halves were missing, and
these cases pin both.

**Holding must leave something behind.** The worker that pauses is not the worker that
resumes; approval arrives later, over HTTP, in another process. If the payload is not
written at the hold there is nothing to publish afterwards, and the failure is silent —
an approved job that completes having published nothing.

**Resuming must not re-write.** The whole point is that a person read *these* pages.
Re-running the writer would publish text nobody reviewed, which is the exact outcome
the gate exists to prevent, arrived at through the feature meant to stop it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.apps.documentation.workflows.composition_workflow import CompositionWorkflow


def _workflow(job_id: int = 1) -> CompositionWorkflow:
    job = SimpleNamespace(id=job_id, config_json={}, project_id=7)
    return CompositionWorkflow(project=SimpleNamespace(id=7), job=job, db=None, sandbox=None)


class TestRouting:
    """When the gate holds, and when it stands aside."""

    @pytest.mark.parametrize(
        "state,expected",
        [
            # Nobody asked for review: QA's verdict does not stop anything.
            ({"requires_human_review": False, "all_approved": False}, "format"),
            # Asked for, and everything passed: there is nothing to look at.
            ({"requires_human_review": True, "all_approved": True}, "format"),
            # Asked for, and something failed: this is the case the gate exists for.
            ({"requires_human_review": True, "all_approved": False}, "await_review"),
            # Already approved by a human — the resumed run must not hold twice.
            (
                {
                    "requires_human_review": True,
                    "all_approved": False,
                    "human_approved": True,
                },
                "format",
            ),
            # An empty state must publish rather than hang: defaults decide this, and
            # defaulting to "hold" would strand every job that never set the keys.
            ({}, "format"),
        ],
    )
    def test_routes(self, state: dict, expected: str) -> None:
        assert _workflow()._route_after_review(state) == expected  # type: ignore[arg-type]


class TestHolding:
    """What the hold writes, and what it deliberately does not."""

    @pytest.mark.asyncio
    async def test_hold_stores_the_pages_and_flags_the_job(self, monkeypatch) -> None:
        saved: dict = {}

        class FakeJobService:
            def __init__(self, db):  # noqa: D107
                pass

            async def hold_for_review(self, job_id, payload):
                saved["job_id"] = job_id
                saved["payload"] = payload

        class FakeSession:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(
            "codelith.db.session.AsyncSessionLocal", lambda: FakeSession()
        )
        monkeypatch.setattr("codelith.services.job_service.JobService", FakeJobService)

        state = {
            "linked_docs": [{"key": "a", "content": "written"}],
            "diagrams": [{"key": "a", "mermaid": "graph TD;"}],
            "review_results": [
                {"key": "a", "review": {"approved": False}},
                {"key": "b", "review": {"approved": True}},
            ],
            "all_approved": False,
            "kb_id": 3,
            # Live objects must not be frozen into the payload.
            "project": object(),
            "sandbox": object(),
        }

        out = await _workflow(job_id=42)._hold_node(state)  # type: ignore[arg-type]

        assert out == {"requires_review": True}, "the task reads this to park the job"
        assert saved["job_id"] == 42
        assert saved["payload"]["linked_docs"] == state["linked_docs"]
        assert saved["payload"]["kb_id"] == 3
        assert "project" not in saved["payload"], "a live object cannot be resumed against"
        assert "sandbox" not in saved["payload"]

    def test_resumable_keys_cover_what_the_tail_reads(self) -> None:
        """
        The formatter and publisher read these. Dropping one from the payload loses a
        page's diagrams or its provenance at publish time, and only on the resumed
        path — which is the path nobody runs by accident.
        """
        keys = set(CompositionWorkflow.RESUMABLE_KEYS)
        for needed in (
            "linked_docs",
            "generated_docs",
            "diagrams",
            "output_formats",
            "pages",
            "kb_id",
            "commit_sha",
            "review_results",
            "validation_results",
        ):
            assert needed in keys, f"the tail reads {needed} and the hold would drop it"

        for live in ("project", "job", "sandbox"):
            assert live not in keys, f"{live} is rebuilt on resume, never stored"


class TestResuming:
    """Approval publishes what was written; it does not commission more."""

    def test_tail_graph_holds_only_the_unrun_stages(self) -> None:
        graph = _workflow()._build_tail_graph()
        nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}

        assert nodes == {"formatter", "publisher"}, (
            "the tail must be exactly the stages that had not run at the hold — "
            "including the writer here would republish text nobody reviewed"
        )

    @pytest.mark.asyncio
    async def test_run_tail_rebuilds_live_objects_and_clears_the_hold(
        self, monkeypatch
    ) -> None:
        seen: dict = {}

        class FakeGraph:
            async def ainvoke(self, state):
                seen.update(state)
                return {"saved_page_ids": [11], "kb_id": 3}

        wf = _workflow(job_id=9)
        monkeypatch.setattr(wf, "_build_tail_graph", lambda: FakeGraph())

        result = await wf.run_tail({"linked_docs": [{"key": "a"}], "kb_id": 3})

        assert seen["project"] is wf.project, "resume publishes against the project as it is now"
        assert seen["job"] is wf.job
        assert seen["human_approved"] is True, "reaching the tail is the approval"
        assert seen["linked_docs"] == [{"key": "a"}]
        assert result["requires_review"] is False, "a published job is no longer waiting"
        assert result["saved_page_ids"] == [11]


class TestClaimedPagesAreHandedBack:
    """
    A run claims its pages before writing and resolves them after. Ending in
    between left the claim permanent, and the cost was not cosmetic: the studio
    polls the site map for as long as any page is `generating`, so one cancelled
    job made the documentation page re-fetch every four seconds, on every visit,
    for the life of the project.

    Every path that ends a run without publishing has to release: cancel, crash,
    and — since the gate — a rejected review.
    """

    @pytest.mark.parametrize(
        "failed,expected",
        [
            # Cancelled: the user stopped it, so the page is simply unwritten again.
            (False, "planned"),
            # Crashed: something was attempted, and saying so is more use than
            # pretending the page was never touched.
            (True, "failed"),
        ],
    )
    @pytest.mark.asyncio
    async def test_release_resets_only_this_job_s_generating_pages(
        self, failed: bool, expected: str
    ) -> None:
        from codelith.apps.documentation.services.site_service import SiteService

        captured: dict = {}

        class FakeResult:
            rowcount = 2

        class FakeDb:
            async def execute(self, stmt, **kw):
                captured["sql"] = str(stmt)
                captured["params"] = stmt.compile().params
                return FakeResult()

            async def commit(self):
                captured["committed"] = True

        svc = SiteService.__new__(SiteService)
        svc.db = FakeDb()  # type: ignore[attr-defined]

        assert await SiteService.release_pages(svc, 43, failed=failed) == 2
        assert captured["committed"] is True

        sql = captured["sql"]
        assert "UPDATE doc_pages" in sql
        # Scoped both ways: another job's pages, and this job's already-published
        # ones, must not be touched.
        assert "job_id" in sql and "status" in sql
        assert captured["params"]["status"] == expected
