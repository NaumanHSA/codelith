"""
Reusing the composition strategy across jobs.

The strategy — audience, tone, whether diagrams are worth drawing — reads this
knowledge base's narratives and stats and nothing else, so a second job against the
same KB was re-deriving an answer it already had. Composing a section page by page
paid for it once per page, ~13s each against a hosted model.

What the cache must not do is answer a question it was not asked: a job spanning two
doc types where only one is known has to miss, or the second doc type silently
inherits the first one's audience.
"""

from __future__ import annotations

import pytest

from codelith.apps.documentation.agents.strategy import CompositionStrategyAgent


class FakeBases:
    """Stands in for KnowledgeBaseRepository's strategy accessors."""

    def __init__(self, stored: dict | None = None) -> None:
        self.stored = stored or {}
        self.merges: list[dict] = []

    async def get_strategy(self, kb_id: int) -> dict:
        return dict(self.stored)

    async def merge_strategy(self, kb_id: int, entries: dict) -> None:
        self.merges.append(entries)
        self.stored.update(entries)


class FakeRepos:
    def __init__(self, bases: FakeBases) -> None:
        self.bases = bases


@pytest.fixture
def agent() -> CompositionStrategyAgent:
    a = CompositionStrategyAgent(db=None, job_id=1)  # type: ignore[arg-type]

    async def _noop(*args, **kwargs):
        return None

    a._emit_log = _noop  # type: ignore[method-assign]
    return a


ARCH = {
    "audience": {"doc_type": "architecture", "audience": "engineers", "tone": "technical"},
    "generate_diagrams": True,
}
API = {
    "audience": {"doc_type": "api", "audience": "integrators", "tone": "precise"},
    "generate_diagrams": False,
}


class TestReading:
    async def test_a_known_doc_type_is_reused(self, agent) -> None:
        repos = FakeRepos(FakeBases({"architecture": ARCH}))
        cached = await agent._cached(repos, 1, ["architecture"])

        assert cached is not None
        assert cached["audiences"] == [ARCH["audience"]]
        assert cached["generate_diagrams"] is True

    async def test_an_empty_cache_misses(self, agent) -> None:
        repos = FakeRepos(FakeBases({}))

        assert await agent._cached(repos, 1, ["architecture"]) is None

    async def test_a_partial_hit_misses(self, agent) -> None:
        """
        The load-bearing one. Returning what is known and quietly dropping the rest
        would give the missing doc type no audience at all.
        """
        repos = FakeRepos(FakeBases({"architecture": ARCH}))

        assert await agent._cached(repos, 1, ["architecture", "api"]) is None

    async def test_diagrams_take_the_stricter_answer(self, agent) -> None:
        """A per-run cost: if either doc type said no, the run does not draw."""
        repos = FakeRepos(FakeBases({"architecture": ARCH, "api": API}))
        cached = await agent._cached(repos, 1, ["architecture", "api"])

        assert cached is not None
        assert cached["generate_diagrams"] is False

    async def test_audiences_come_back_in_the_order_asked_for(self, agent) -> None:
        repos = FakeRepos(FakeBases({"architecture": ARCH, "api": API}))
        cached = await agent._cached(repos, 1, ["api", "architecture"])

        assert [a["doc_type"] for a in cached["audiences"]] == ["api", "architecture"]


class TestWriting:
    async def test_what_was_decided_is_stored_per_doc_type(self, agent) -> None:
        bases = FakeBases()
        strategy = {
            "audiences": [ARCH["audience"], API["audience"]],
            "generate_diagrams": True,
        }
        await agent._remember(FakeRepos(bases), 1, ["architecture", "api"], strategy)

        assert set(bases.stored) == {"architecture", "api"}
        assert bases.stored["architecture"]["audience"] == ARCH["audience"]

    async def test_a_doc_type_the_model_ignored_is_not_stored(self, agent) -> None:
        """Storing a placeholder would mean a wrong answer reused for ever."""
        bases = FakeBases()
        strategy = {"audiences": [ARCH["audience"]], "generate_diagrams": True}
        await agent._remember(FakeRepos(bases), 1, ["architecture", "api"], strategy)

        assert set(bases.stored) == {"architecture"}

    async def test_a_failing_cache_write_never_fails_the_job(self, agent) -> None:
        class Exploding(FakeBases):
            async def merge_strategy(self, kb_id: int, entries: dict) -> None:
                raise RuntimeError("database went away")

        strategy = {"audiences": [ARCH["audience"]], "generate_diagrams": True}
        # The strategy still governs this run; the next job simply pays for it again.
        await agent._remember(FakeRepos(Exploding()), 1, ["architecture"], strategy)

    async def test_a_round_trip_reuses_what_it_stored(self, agent) -> None:
        bases = FakeBases()
        repos = FakeRepos(bases)
        strategy = {"audiences": [ARCH["audience"]], "generate_diagrams": True}

        assert await agent._cached(repos, 1, ["architecture"]) is None
        await agent._remember(repos, 1, ["architecture"], strategy)
        cached = await agent._cached(repos, 1, ["architecture"])

        assert cached is not None
        assert cached["audiences"] == [ARCH["audience"]]
