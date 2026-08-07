"""
Addressing one heading inside a page.

Every case here is a way a rewrite could quietly edit the wrong thing, or lose prose
that was not being rewritten. The splice is the dangerous operation in the whole
feature: it replaces part of a stored document, and the parts it is not replacing
have to come back exactly as they went in.
"""

from __future__ import annotations

import pytest

from app.knowledge.blocks import (
    find_blocks,
    outline,
    replace_block,
    split_blocks,
    word_count,
)

PAGE = """Some opening prose that belongs to no section.

## First section

Body of the first.

### A nested heading

Nested body.

## Second section

Body of the second.
"""


class TestSplitting:
    def test_sections_are_the_double_hash_headings(self) -> None:
        blocks = split_blocks(PAGE)

        assert [b.title for b in blocks] == ["First section", "Second section"]

    def test_a_section_carries_its_nested_headings(self) -> None:
        """Rewriting a `##` means rewriting what a reader sees as that section."""
        first = split_blocks(PAGE)[0]

        assert "### A nested heading" in first.text
        assert "Nested body." in first.text
        assert "Second section" not in first.text

    def test_prose_before_the_first_heading_belongs_to_no_block(self) -> None:
        blocks = split_blocks(PAGE)

        assert all("opening prose" not in b.text for b in blocks)

    def test_anchors_match_the_ids_the_studio_stamps(self) -> None:
        assert [b.anchor for b in split_blocks(PAGE)] == ["first-section", "second-section"]

    def test_the_body_excludes_the_heading_line(self) -> None:
        first = split_blocks(PAGE)[0]

        assert not first.body.startswith("##")
        assert first.body.startswith("Body of the first.")

    @pytest.mark.parametrize("markdown", ["", "no headings at all", "\n\n"])
    def test_a_page_with_no_sections_yields_none(self, markdown) -> None:
        assert split_blocks(markdown) == []


class TestFences:
    """A `##` inside a code fence is not a heading. Getting this wrong splits a page
    documenting Markdown — or any page with a shell snippet — into nonsense."""

    def test_a_hash_inside_a_fence_is_not_a_section(self) -> None:
        page = "## Real\n\n```bash\n## not a heading\necho hi\n```\n\nstill the real one.\n"
        blocks = split_blocks(page)

        assert [b.title for b in blocks] == ["Real"]
        assert "still the real one." in blocks[0].text

    def test_a_section_after_a_fence_is_still_found(self) -> None:
        page = "## One\n\n```\n## fake\n```\n\n## Two\n\nbody\n"

        assert [b.title for b in split_blocks(page)] == ["One", "Two"]


class TestAmbiguity:
    def test_two_headings_with_the_same_title_both_come_back(self) -> None:
        """
        `anchor_id` maps them to one id and the studio does not disambiguate either,
        so the caller has to refuse rather than edit whichever came first.
        """
        page = "## Errors\n\nfirst\n\n## Other\n\nx\n\n## Errors\n\nsecond\n"
        found = find_blocks(page, "errors")

        assert len(found) == 2
        assert "first" in found[0].text
        assert "second" in found[1].text

    def test_an_unknown_anchor_finds_nothing(self) -> None:
        assert find_blocks(PAGE, "does-not-exist") == []


class TestReplacing:
    def test_everything_outside_the_block_survives_exactly(self) -> None:
        block = find_blocks(PAGE, "first-section")[0]
        out = replace_block(PAGE, block, "## First section\n\nRewritten.")

        assert "Some opening prose that belongs to no section." in out
        assert "## Second section" in out
        assert "Body of the second." in out
        assert "Body of the first." not in out
        assert "Rewritten." in out

    def test_the_nested_heading_goes_with_the_block_it_belonged_to(self) -> None:
        block = find_blocks(PAGE, "first-section")[0]
        out = replace_block(PAGE, block, "## First section\n\nRewritten.")

        assert "### A nested heading" not in out

    def test_replacing_the_last_section_keeps_the_earlier_ones(self) -> None:
        block = find_blocks(PAGE, "second-section")[0]
        out = replace_block(PAGE, block, "## Second section\n\nNew tail.")

        assert "## First section" in out
        assert "New tail." in out
        assert "Body of the second." not in out

    def test_a_replacement_without_a_heading_gets_one_back(self) -> None:
        """
        Losing the heading would orphan every `#anchor` link pointing at it, and the
        model answering with bare prose is a normal failure.
        """
        block = find_blocks(PAGE, "first-section")[0]
        out = replace_block(PAGE, block, "Just prose, no heading.")

        assert "## First section" in out
        assert "Just prose, no heading." in out

    def test_a_replacement_that_brings_its_own_heading_is_not_doubled(self) -> None:
        block = find_blocks(PAGE, "first-section")[0]
        out = replace_block(PAGE, block, "## First section\n\nBody.")

        assert out.count("## First section") == 1

    def test_an_empty_replacement_is_refused(self) -> None:
        block = find_blocks(PAGE, "first-section")[0]

        with pytest.raises(ValueError, match="nothing"):
            replace_block(PAGE, block, "   \n\n ")

    def test_a_round_trip_with_identical_text_changes_nothing_meaningful(self) -> None:
        block = find_blocks(PAGE, "first-section")[0]
        out = replace_block(PAGE, block, block.text)

        assert out.split() == PAGE.split()

    def test_the_page_is_still_splittable_afterwards(self) -> None:
        """The splice must not corrupt the structure for the next rewrite."""
        block = find_blocks(PAGE, "first-section")[0]
        out = replace_block(PAGE, block, "## First section\n\n### New child\n\nx")

        assert [b.title for b in split_blocks(out)] == ["First section", "Second section"]


class TestOutline:
    def test_the_studio_gets_anchor_title_and_size(self) -> None:
        assert outline(PAGE) == [
            # "Body of the first." + "A nested heading" + "Nested body." — the `###`
            # marker is not a word the reader sees.
            {"anchor": "first-section", "title": "First section", "words": 9},
            {"anchor": "second-section", "title": "Second section", "words": 4},
        ]

    def test_heading_markers_are_not_counted_as_words(self) -> None:
        # "A heading" (2) + "two words" (2). The `###` is markup, not a word.
        assert word_count("### A heading\n\ntwo words") == 4
