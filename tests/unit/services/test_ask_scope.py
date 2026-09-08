"""
What happens to a question the gate does not send to the code.

The gate itself is measured in `tests/unit/knowledge/test_scope.py`. These are about
the wiring: that a declined question never builds an evidence bundle, that the events
the studio and the persistence layer read still arrive in the shape they expect, and
that a `code` verdict changes nothing about the path that was already there.

The retrieval assertion is the one that matters. A gate that decides correctly and
then searches anyway has cost a model call to change nothing, and the symptom —
an answer about the repository to a question about France — is exactly what it was
added to remove.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.apps.ask import service as ask_service
from codelith.apps.ask.service import AskService
from codelith.knowledge.questions import Evidence, EvidenceBundle, QuestionPlan
from codelith.knowledge.scope import CodebaseProfile, ScopeVerdict

PROJECT = SimpleNamespace(id=1, name="psephos")


@pytest.fixture
def wired(monkeypatch):
    """
    Stands the service up with a scripted gate and a router that must not run.

    `routed` records whether retrieval happened at all: that is the assertion, and it
    is invisible from the events on their own — a declined question and a search that
    found nothing produce answers that look alike from outside.
    """

    def _install(verdict: ScopeVerdict, *, answer: str = "the API is in ballots/api.py"):
        state = {"routed": 0, "answered": 0}

        async def fake_usable_kb(self, project_id):
            return SimpleNamespace(id=7, status="ready")

        async def fake_load_profile(db, kb, project_name):
            return CodebaseProfile.build(project_name)

        class _Gate:
            def __init__(self, profile):
                self.profile = profile

            async def judge(self, question, history=None):
                return verdict

        class _Router:
            def __init__(self, *a, **k):
                pass

            async def gather(self, question, **kwargs):
                state["routed"] += 1
                bundle = EvidenceBundle(plan=QuestionPlan(question=question))
                bundle.items = [
                    Evidence(kind="code", title="ballots/api.py:1-20", body="…", why="match")
                ]
                return bundle

        async def fake_answer(self, messages, bundle, kb_id, project_id, spec):
            state["answered"] += 1
            yield {"type": "token", "text": answer}

        monkeypatch.setattr(AskService, "_usable_kb", fake_usable_kb)
        monkeypatch.setattr(AskService, "_answer", fake_answer)
        monkeypatch.setattr(ask_service, "load_profile", fake_load_profile)
        monkeypatch.setattr(ask_service, "ScopeGate", _Gate)
        monkeypatch.setattr(ask_service, "QuestionRouter", _Router)
        return state

    return _install


async def _events(question: str, history: list[dict] | None = None) -> list[dict]:
    return [e async for e in AskService(None).stream(PROJECT, question, history)]


class TestADeclinedQuestion:
    async def test_the_code_is_never_searched(self, wired) -> None:
        state = wired(
            ScopeVerdict(verdict="off_topic", reason="geography", reply="Not from here.")
        )

        await _events("what is the capital of France")

        assert state["routed"] == 0
        assert state["answered"] == 0

    async def test_the_reply_arrives_the_way_every_answer_does(self, wired) -> None:
        """One `token` event and a `done`, so the studio renders it down the path it
        already has and the API stores it like any other turn."""
        wired(ScopeVerdict(verdict="off_topic", reason="geography", reply="Not from here."))

        events = await _events("what is the capital of France")
        kinds = [e["type"] for e in events]

        assert kinds == ["scope", "token", "usage", "done"]
        assert events[-1]["text"] == "Not from here."
        assert events[-1]["citations"] == []

    async def test_no_evidence_event_is_emitted(self, wired) -> None:
        """Its absence is the honest shape of what happened: nothing was retrieved,
        so there is nothing to show in the sources panel."""
        wired(ScopeVerdict(verdict="chat", reason="a greeting", reply="Hello."))

        assert "evidence" not in [e["type"] for e in await _events("hey")]

    async def test_the_verdict_is_reported_before_anything_else(self, wired) -> None:
        wired(ScopeVerdict(verdict="off_topic", reason="geography", reply="no", decided_by="llm"))

        first = (await _events("what is the capital of France"))[0]

        assert first == {
            "type": "scope",
            "verdict": "off_topic",
            "reason": "geography",
            "decided_by": "llm",
        }


class TestAQuestionAboutTheCode:
    async def test_retrieval_runs_as_before(self, wired) -> None:
        state = wired(ScopeVerdict(reason="names the ballot ingest"))

        kinds = [e["type"] for e in await _events("how does ballot ingest work")]

        assert state["routed"] == 1 and state["answered"] == 1
        assert kinds[:3] == ["scope", "evidence", "token"]

    async def test_the_gate_can_be_switched_off(self, wired, monkeypatch) -> None:
        """The judgement is made by whichever model is configured locally, and its
        one bad outcome is a real question declined. That needs a switch, not a
        release."""
        state = wired(ScopeVerdict(verdict="off_topic", reply="no"))
        monkeypatch.setattr(
            ask_service, "get_settings", lambda: SimpleNamespace(ASK_SCOPE_GATE=False)
        )

        events = await _events("what is the capital of France")

        assert state["routed"] == 1
        assert events[0]["decided_by"] == "disabled"


class TestItFailsOpen:
    async def test_a_profile_that_cannot_be_read_still_answers(self, wired, monkeypatch) -> None:
        """Reading the profile is a database call and can fail for reasons that have
        nothing to do with the question. The gate improves a working feature; it must
        never be why one stops working."""
        state = wired(ScopeVerdict(verdict="off_topic", reply="no"))

        async def boom(db, kb, project_name):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(ask_service, "load_profile", boom)

        events = await _events("what is the capital of France")

        assert state["routed"] == 1
        assert events[0]["decided_by"] == "fallback"
