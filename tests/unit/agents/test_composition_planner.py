"""
Section-level planning.

The unit under test is the allocation: one call for a whole section, so that no two
pages of it can independently claim the same material. C1 measured what happens
without it — four pages planned in isolation, and the overview page covering ground
that four other sections own.

A section-wide call also has a bigger blast radius than a per-page one: one bad
response costs a section's structure rather than a page's. So the per-page planner
stays as the net, and most of what is asserted here is that it fires.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.composition.planner import CompositionPlannerAgent

SETTINGS = SimpleNamespace(SITE_MAX_HEADINGS_PER_PAGE=6)

KNOWN = {"app/api.py", "app/models.py", "app/worker.py"}

PAGES = [
    {
        "id": 1,
        "address": "architecture/overview",
        "section_slug": "architecture",
        "slug": "overview",
        "title": "Overview",
        "doc_type": "architecture",
        "intent": "How the parts relate",
        "key_files": ["app/api.py"],
    },
    {
        "id": 2,
        "address": "architecture/data-model",
        "section_slug": "architecture",
        "slug": "data-model",
        "title": "Data Model",
        "doc_type": "architecture",
        "intent": "The schemas",
        "key_files": ["app/models.py"],
    },
]


@pytest.fixture
def agent() -> CompositionPlannerAgent:
    return CompositionPlannerAgent(db=None, job_id=1)  # type: ignore[arg-type]


class TestGrouping:
    def test_pages_group_by_section_preserving_order(self, agent) -> None:
        pages = [
            {"section_slug": "api", "address": "api/a"},
            {"section_slug": "guides", "address": "guides/x"},
            {"section_slug": "api", "address": "api/b"},
        ]
        groups = agent._by_section(pages)

        assert list(groups) == ["api", "guides"]
        assert [p["address"] for p in groups["api"]] == ["api/a", "api/b"]


class TestSectionResponseValidation:
    def test_splits_a_response_into_per_page_plans(self, agent) -> None:
        raw = {
            "pages": [
                {
                    "address": "architecture/overview",
                    "sections": [
                        {"name": "Shape", "focus": "how it fits", "key_files": ["app/api.py"]},
                    ],
                },
                {
                    "address": "architecture/data-model",
                    "sections": [
                        {"name": "Tables", "focus": "the schema", "key_files": ["app/models.py"]},
                    ],
                },
            ]
        }
        out = agent._validate_section(
            raw, ["architecture/overview", "architecture/data-model"], KNOWN, SETTINGS
        )

        assert set(out) == {"architecture/overview", "architecture/data-model"}
        assert out["architecture/overview"][0]["name"] == "Shape"

    def test_invented_paths_are_still_discarded(self, agent) -> None:
        """The whole-KB existence check must survive the move to section scope."""
        raw = {
            "pages": [
                {
                    "address": "architecture/overview",
                    "sections": [
                        {
                            "name": "Shape",
                            "focus": "how it fits",
                            "key_files": ["app/api.py", "app/does_not_exist.py"],
                        }
                    ],
                }
            ]
        }
        out = agent._validate_section(raw, ["architecture/overview"], KNOWN, SETTINGS)

        assert out["architecture/overview"][0]["key_files"] == ["app/api.py"]

    def test_pages_the_model_invented_are_dropped(self, agent) -> None:
        """An address with no page behind it has no `page_id` to write to."""
        raw = {
            "pages": [
                {
                    "address": "architecture/imaginary",
                    "sections": [{"name": "X", "focus": "y", "key_files": []}],
                }
            ]
        }
        assert agent._validate_section(raw, ["architecture/overview"], KNOWN, SETTINGS) == {}

    def test_headings_are_capped(self, agent) -> None:
        raw = {
            "pages": [
                {
                    "address": "architecture/overview",
                    "sections": [
                        {"name": f"H{i}", "focus": "f", "key_files": []} for i in range(20)
                    ],
                }
            ]
        }
        out = agent._validate_section(raw, ["architecture/overview"], KNOWN, SETTINGS)

        assert len(out["architecture/overview"]) == SETTINGS.SITE_MAX_HEADINGS_PER_PAGE

    @pytest.mark.parametrize("raw", [None, {}, {"pages": []}, {"pages": ["nonsense"]}])
    def test_unusable_responses_allocate_nothing(self, agent, raw) -> None:
        """Each of these must leave the caller to fall back, not raise."""
        assert agent._validate_section(raw, ["architecture/overview"], KNOWN, SETTINGS) == {}


class TestSiteMapRendering:
    def test_excluding_a_section_hides_all_of_its_pages(self, agent) -> None:
        site_map = {
            "sections": [
                {"slug": "architecture", "pages": [{"slug": "overview", "title": "Overview"}]},
                {"slug": "api", "pages": [{"slug": "endpoints", "title": "Endpoints"}]},
            ]
        }
        rendered = agent._render_site_map(site_map, exclude_section="architecture")

        assert "api/endpoints" in rendered
        assert "architecture/overview" not in rendered

    def test_excluding_one_page_keeps_its_siblings(self, agent) -> None:
        site_map = {
            "sections": [
                {
                    "slug": "architecture",
                    "pages": [
                        {"slug": "overview", "title": "Overview"},
                        {"slug": "data-model", "title": "Data Model"},
                    ],
                }
            ]
        }
        rendered = agent._render_site_map(site_map, exclude="architecture/overview")

        assert "architecture/data-model" in rendered
        assert "architecture/overview" not in rendered


class _Module:
    def __init__(self, i: int) -> None:
        self.id = i
        self.path = f"app/m{i}"
        self.role = "service"
        self.summary = f"module {i}"
        self.files_json = ["app/api.py"]


class _Modules:
    async def list_by_kb(self, kb_id, roles=None, include_tests=False, limit=40):
        return [_Module(1), _Module(2)]


class _Repos:
    modules = _Modules()


def _plan_args(agent, group=PAGES):
    """Everything `_plan_section` needs, with logging stubbed out."""

    async def _noop(*a, **k):
        return None

    agent._emit_log = _noop  # type: ignore[method-assign]
    return dict(
        section_slug="architecture",
        group=group,
        project=SimpleNamespace(name="widgets"),
        site_map={"sections": [{"slug": "architecture", "title": "Architecture", "pages": []}]},
        overview="",
        repos=_Repos(),
        kb_id=1,
        facts="",
        strategy={},
        known_files=KNOWN,
    )


class TestOneCallPerSection:
    async def test_a_two_page_section_makes_one_planning_call(self, agent) -> None:
        calls = []

        async def fake(messages, task_type="plan", retries=3):
            calls.append(messages)
            return {
                "pages": [
                    {
                        "address": p["address"],
                        "sections": [{"name": "H", "focus": "f", "key_files": ["app/api.py"]}],
                    }
                    for p in PAGES
                ]
            }

        agent._call_llm_json = fake  # type: ignore[method-assign]
        plans = await agent._plan_section(**_plan_args(agent))

        assert len(calls) == 1, "the whole point of C4 is one call, not one per page"
        assert set(plans) == {p["address"] for p in PAGES}
        assert plans["architecture/overview"]["page_id"] == 1

    async def test_a_one_page_section_skips_the_section_call(self, agent) -> None:
        """
        Nothing to allocate between. A single-page section call is the per-page
        prompt with extra scaffolding, and a bigger blast radius for no gain.
        """
        seen = []

        async def fake(messages, task_type="plan", retries=3):
            seen.append(messages)
            return {"sections": [{"name": "H", "focus": "f", "key_files": ["app/api.py"]}]}

        agent._call_llm_json = fake  # type: ignore[method-assign]
        plans = await agent._plan_section(**_plan_args(agent, group=[PAGES[0]]))

        assert len(seen) == 1
        assert plans["architecture/overview"]["sections"][0]["name"] == "H"

    async def test_a_failed_section_call_falls_back_to_planning_each_page(self, agent) -> None:
        responses = [None]  # the section call returns nothing usable

        async def fake(messages, task_type="plan", retries=3):
            if responses:
                responses.pop()
                return None
            return {"sections": [{"name": "PerPage", "focus": "f", "key_files": []}]}

        agent._call_llm_json = fake  # type: ignore[method-assign]
        plans = await agent._plan_section(**_plan_args(agent))

        assert set(plans) == {p["address"] for p in PAGES}
        for plan in plans.values():
            assert plan["sections"][0]["name"] == "PerPage"

    async def test_a_page_the_model_forgot_is_planned_on_its_own(self, agent) -> None:
        """Partial allocation must not leave a page with no headings at all."""

        async def fake(messages, task_type="plan", retries=3):
            # Section call answers for one page only; the per-page retry answers the rest.
            if any("EVERY page" in m["content"] for m in messages):
                return {
                    "pages": [
                        {
                            "address": "architecture/overview",
                            "sections": [
                                {"name": "Allocated", "focus": "f", "key_files": []}
                            ],
                        }
                    ]
                }
            return {"sections": [{"name": "PerPage", "focus": "f", "key_files": []}]}

        agent._call_llm_json = fake  # type: ignore[method-assign]
        plans = await agent._plan_section(**_plan_args(agent))

        assert plans["architecture/overview"]["sections"][0]["name"] == "Allocated"
        assert plans["architecture/data-model"]["sections"][0]["name"] == "PerPage"


class TestPageRendering:
    def test_only_anchor_files_the_kb_knows_are_offered(self, agent) -> None:
        pages = [{**PAGES[0], "key_files": ["app/api.py", "app/ghost.py"]}]
        rendered = agent._render_pages(pages, KNOWN)

        assert "app/api.py" in rendered
        assert "app/ghost.py" not in rendered

    def test_every_page_carries_its_purpose(self, agent) -> None:
        rendered = agent._render_pages(PAGES, KNOWN)

        for page in PAGES:
            assert page["address"] in rendered
            assert page["intent"] in rendered
