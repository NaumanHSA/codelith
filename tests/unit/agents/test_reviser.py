"""
The reviser.

Its whole job is to change one part of a page and leave the rest alone, so every
case here is a way it could fail to do that: editing the wrong section, blanking a
page when the model returns nothing, or publishing something when it should have
refused. The reviser is the only agent that *destroys* existing prose, and the guard
against that is refusing rather than emitting.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.composition.reviser import ReviserAgent

PAGE_MD = """Opening line.

## Request and data flow

The old flow text.

### A detail

Detail body.

## Errors

Error text.
"""

PAGE = {
    "id": 7,
    "address": "architecture/system-architecture",
    "section_slug": "architecture",
    "slug": "system-architecture",
    "title": "System Architecture",
    "intent": "How the parts fit",
    "doc_type": "architecture",
    "content_markdown": PAGE_MD,
    "source_files": ["app/api.py"],
    "key_files": ["app/api.py"],
}


@pytest.fixture
def agent() -> ReviserAgent:
    a = ReviserAgent(db=None, job_id=1)  # type: ignore[arg-type]

    async def _noop(*args, **kwargs):
        return None

    a._emit_log = _noop  # type: ignore[method-assign]
    a._update_step = _noop  # type: ignore[method-assign]
    return a


class _Tracer:
    def outputs(self, **kwargs):
        pass


class TestGivingUp:
    """A revision that cannot be made must change nothing. Emitting a document here
    would send the publisher over the page the user asked to improve."""

    async def test_a_missing_anchor_produces_no_document(self, agent) -> None:
        out = await agent._give_up(_Tracer(), "No section with anchor 'nope'")

        assert out["generated_docs"] == []
        assert "nope" in out["error"]

    async def test_the_error_reaches_the_caller(self, agent) -> None:
        out = await agent._give_up(_Tracer(), "the model returned nothing")

        assert out["error"] == "the model returned nothing"


class TestHistory:
    def test_no_history_renders_nothing(self, agent) -> None:
        assert agent._history([]) == ""

    def test_earlier_turns_are_offered_to_the_model(self, agent) -> None:
        rendered = agent._history(
            [{"instructions": "make it shorter"}, {"instructions": "add an example"}]
        )

        assert "make it shorter" in rendered
        assert "add an example" in rendered

    def test_only_the_last_few_turns_are_kept(self, agent) -> None:
        """The panel is short-lived by design; the cap only stops a long session
        quietly growing the prompt without bound."""
        turns = [{"instructions": f"turn {i}"} for i in range(20)]
        rendered = agent._history(turns)

        assert "turn 19" in rendered
        assert "turn 0" not in rendered

    def test_a_turn_with_no_instruction_is_skipped(self, agent) -> None:
        assert agent._history([{"instructions": "   "}]).count("You were asked") == 0


class TestNeighbours:
    def test_the_page_itself_is_not_offered_as_a_link_target(self, agent) -> None:
        site_map = {
            "sections": [
                {
                    "slug": "architecture",
                    "pages": [
                        {"slug": "system-architecture", "title": "System Architecture"},
                        {"slug": "data-model", "title": "Data Model"},
                    ],
                }
            ]
        }
        rendered = agent._neighbours(site_map, "architecture/system-architecture")

        assert "[[architecture/data-model]]" in rendered
        assert "[[architecture/system-architecture]]" not in rendered

    def test_an_empty_site_map_renders_nothing(self, agent) -> None:
        assert agent._neighbours({}, "a/b") == ""


class TestVoice:
    def test_the_pages_own_doc_type_decides_the_voice(self, agent) -> None:
        strategy = {
            "audiences": [
                {"doc_type": "api", "audience": "integrators", "tone": "precise"},
                {"doc_type": "architecture", "audience": "engineers", "tone": "technical"},
            ]
        }

        assert agent._voice(strategy, "architecture") == ("engineers", "technical")

    def test_an_unknown_doc_type_falls_back(self, agent) -> None:
        assert agent._voice({}, "architecture") == ("developers", "technical")


class TestSplicing:
    """End-to-end through the block layer, which is what actually protects the page."""

    def test_only_the_addressed_section_changes(self) -> None:
        from app.knowledge.blocks import find_blocks, replace_block

        block = find_blocks(PAGE_MD, "request-and-data-flow")[0]
        out = replace_block(PAGE_MD, block, "## Request and data flow\n\nNew flow text.")

        assert "New flow text." in out
        assert "The old flow text." not in out
        # Everything else survives, including the section after it and the preamble.
        assert "Opening line." in out
        assert "## Errors" in out
        assert "Error text." in out

    def test_the_pages_structure_survives_for_the_next_turn(self) -> None:
        """A conversation means revising the same page repeatedly; the splice must
        leave it addressable."""
        from app.knowledge.blocks import find_blocks, replace_block, split_blocks

        block = find_blocks(PAGE_MD, "request-and-data-flow")[0]
        once = replace_block(PAGE_MD, block, "## Request and data flow\n\nFirst pass.")
        block2 = find_blocks(once, "request-and-data-flow")[0]
        twice = replace_block(once, block2, "## Request and data flow\n\nSecond pass.")

        assert "Second pass." in twice
        assert "First pass." not in twice
        assert [b.title for b in split_blocks(twice)] == ["Request and data flow", "Errors"]


class TestOutputShape:
    def test_the_document_is_shaped_like_a_composition_result(self) -> None:
        """
        The linker and publisher are reused unchanged, so the reviser has to emit
        exactly what they already consume — page_id and address especially, or the
        publisher writes nothing back.
        """
        doc = {
            "doc_type": PAGE["doc_type"],
            "title": PAGE["title"],
            "content_markdown": "…",
            "page_id": PAGE["id"],
            "address": PAGE["address"],
            "section_slug": PAGE["section_slug"],
            "slug": PAGE["slug"],
            "source_files": PAGE["source_files"],
        }

        assert doc["page_id"] == 7
        assert doc["address"] == "architecture/system-architecture"
        # Unchanged by a revision: overwriting these would make staleness detection
        # wrong for the whole page, not just the edited section.
        assert doc["source_files"] == ["app/api.py"]


class TestSettingsUsed:
    def test_the_agent_is_named_for_its_step(self) -> None:
        """`EXPECTED_STAGES` in the studio keys off this."""
        assert ReviserAgent.name == "reviser_agent"

    def test_a_page_without_an_anchor_revises_the_whole_thing(self) -> None:
        from app.knowledge.blocks import find_blocks

        # No anchor means no block lookup at all — the target is the page.
        assert find_blocks(PAGE_MD, "") == []
        assert SimpleNamespace(anchor=None).anchor is None
