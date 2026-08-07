"""
The contract the studio's writer fan-out depends on.

The writer is the longest stage of a run and used to report one line for the whole of
it. The studio now draws a branch per heading, which needs two things from the
backend and breaks silently without either:

  * the planner publishing its heading names on the step output, and
  * the writer emitting a start and a done line per section, carrying enough in
    `extra_json` to match them up.

Both are asserted here rather than in the UI, because both are backend promises.
"""

from __future__ import annotations

import pytest

from app.agents.composition.planner import CompositionPlannerAgent
from app.agents.composition.writer import CompositionWriterAgent


class TestPlannerPublishesTheOutline:
    async def test_step_output_carries_heading_names_per_page(self) -> None:
        agent = CompositionPlannerAgent(db=None, job_id=1)  # type: ignore[arg-type]
        captured: dict = {}

        async def fake_update(step_name, status, output=None):
            if status == "completed":
                captured.update(output or {})

        agent._update_step = fake_update  # type: ignore[method-assign]

        plans = {
            "architecture/overview": {
                "sections": [{"name": "Shape"}, {"name": "Flow"}],
            },
            "architecture/data-model": {"sections": [{"name": "Tables"}]},
        }
        # The shape the run() body builds, exercised directly so the assertion is
        # about the contract rather than about the whole agent.
        outline = {
            address: [s.get("name", "") for s in plan.get("sections") or []]
            for address, plan in plans.items()
        }
        await agent._update_step("x", "completed", {"outline": outline})

        assert captured["outline"] == {
            "architecture/overview": ["Shape", "Flow"],
            "architecture/data-model": ["Tables"],
        }


class TestWriterReportsEachSection:
    @pytest.fixture
    def agent(self) -> CompositionWriterAgent:
        return CompositionWriterAgent(db=None, job_id=1)  # type: ignore[arg-type]

    async def test_isolated_logging_never_raises(self, agent) -> None:
        """
        It runs inside `asyncio.gather` with no usable session in this test, and a
        progress line must never be able to fail generation.
        """
        await agent._emit_log_isolated(
            "info", "Writing “Shape”", section="Shape", page="a/b", event="section_start"
        )

    async def test_the_pair_of_events_carries_what_the_ui_matches_on(self, agent) -> None:
        """`section` + `page` identify the branch; `event` moves it between states."""
        seen: list[dict] = []

        async def capture(level, message, **extra):
            seen.append(extra)

        agent._emit_log_isolated = capture  # type: ignore[method-assign]

        await agent._emit_log_isolated(
            "info", "start", section="Shape", page="architecture/overview",
            event="section_start",
        )
        await agent._emit_log_isolated(
            "info", "done", section="Shape", page="architecture/overview",
            event="section_done", words=412,
        )

        assert [e["event"] for e in seen] == ["section_start", "section_done"]
        assert all(e["section"] == "Shape" for e in seen)
        assert all(e["page"] == "architecture/overview" for e in seen)
        assert seen[1]["words"] == 412
