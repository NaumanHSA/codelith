"""
Citations that resolve, and citations that honestly do not.

A written page's inline code spans are a mixture. Measured across the pages on this
machine: real paths (`src/util/errors.js`), module names (`src.draw`), types
(`Image.Image`), and files that exist in the repository but were never indexed
(`package.json`). Fourteen of twenty-eight spans on one project resolve to something
the knowledge base can show; five of ten on the other.

So the rule under all of this is the same one `rewrite_links` follows for pages: link
only what is actually there, and leave everything else exactly as it was. A link that
goes nowhere is worse than text that never promised anywhere to go.
"""

from __future__ import annotations

import pytest

from codelith.apps.documentation.formatters.site_tree import (
    SourceFile,
    cited_paths,
    link_citations,
    source_slug,
)


def sources(*paths: str) -> dict[str, SourceFile]:
    taken: set[str] = set()
    return {p: SourceFile(path=p, slug=source_slug(p, taken)) for p in sorted(paths)}


class TestWhatGetsLinked:
    def test_a_path_the_site_has_source_for(self):
        out = link_citations(
            "See `src/util/errors.js` for the codes.", sources("src/util/errors.js"), "../source/"
        )
        assert out == "See [`src/util/errors.js`](../source/src-util-errors-js.html) for the codes."

    def test_a_path_it_does_not_stays_exactly_as_it_was(self):
        """`package.json` is real, in the repository, and was never indexed."""
        text = "Add it to `package.json` first."
        assert link_citations(text, sources("src/util/errors.js"), "../source/") == text

    @pytest.mark.parametrize("span", ["src.draw", "Image.Image", "ocr_data_toolkit.data"])
    def test_a_module_or_a_type_is_not_a_path(self, span):
        text = f"Handled by `{span}`."
        assert link_citations(text, sources("src/draw/hole.js"), "../source/") == text

    def test_nothing_to_link_against_leaves_the_page_untouched(self):
        text = "See `src/util/errors.js`."
        assert link_citations(text, {}, "../source/") == text

    def test_every_occurrence_is_linked_not_just_the_first(self):
        out = link_citations(
            "`a.py` then `a.py` again", sources("a.py"), "../source/"
        )
        assert out.count("../source/a-py.html") == 2


class TestRanges:
    def test_a_range_becomes_the_anchor(self):
        out = link_citations("`src/x.js:12-30`", sources("src/x.js"), "../source/")
        assert out == "[`src/x.js:12-30`](../source/src-x-js.html#L12-L30)"

    def test_a_single_line_too(self):
        out = link_citations("`src/x.js:12`", sources("src/x.js"), "../source/")
        assert out == "[`src/x.js:12`](../source/src-x-js.html#L12)"

    def test_the_visible_text_keeps_the_range(self):
        """The reader asked about lines 12-30; the link should still say so."""
        assert "`src/x.js:12-30`" in link_citations(
            "`src/x.js:12-30`", sources("src/x.js"), "../source/"
        )


class TestWhatMustNotBeTouched:
    def test_code_inside_a_fence_is_being_shown_not_referred_to(self):
        """A sample that happens to contain a filename is not a citation of it, and
        an anchor inside a `<pre>` is a link in the middle of source."""
        page = "```js\nimport x from 'a.py'\n// see `a.py`\n```\n\nAnd `a.py` outside."
        out = link_citations(page, sources("a.py"), "../source/")
        assert out.count("../source/a-py.html") == 1
        assert "// see `a.py`" in out

    def test_a_tilde_fence_counts_too(self):
        page = "~~~\n`a.py`\n~~~"
        assert link_citations(page, sources("a.py"), "../source/") == page

    def test_a_span_already_inside_a_link_is_left_alone(self):
        """Wrapping it twice produces `[[`x`](a)](b)`, which renders as neither."""
        text = "[`a.py`](../source/a-py.html)"
        assert link_citations(text, sources("a.py"), "../source/") == text

    def test_an_unclosed_fence_does_not_swallow_the_rest_of_the_page(self):
        """It does swallow it, and that is the safe direction: nothing is linked
        rather than links appearing inside what may be a code block."""
        page = "```\nstart\n\n`a.py`"
        assert link_citations(page, sources("a.py"), "../source/") == page


class TestSlugs:
    def test_a_path_becomes_a_filename(self):
        assert source_slug("src/util/errors.js", set()) == "src-util-errors-js"

    def test_collisions_are_broken_deterministically(self):
        """`a/b.js` and `a-b.js` both sanitise to `a-b-js`. The caller iterates a
        sorted list, so the suffix lands on the same file on every rebuild and a
        published URL does not move."""
        taken: set[str] = set()
        assert source_slug("a/b.js", taken) == "a-b-js"
        assert source_slug("a-b.js", taken) == "a-b-js-2"

    def test_a_path_with_nothing_usable_still_gets_a_name(self):
        assert source_slug("///", set()) == "file"


class TestFindingCandidates:
    def test_it_finds_paths(self):
        found = cited_paths("See `src/a.js` and `pkg/b.py:10-20`.")
        assert found == {"src/a.js", "pkg/b.py"}

    def test_it_ignores_prose_with_no_extension(self):
        """Without this the candidate set fills with every function name and flag in
        the page, and each one costs a database round trip to discover it is not a
        file."""
        assert cited_paths("Call `authenticate` with `--force`.") == set()

    def test_it_ignores_spans_containing_spaces(self):
        assert cited_paths("`npm run build`") == set()

    def test_it_skips_fenced_blocks(self):
        assert cited_paths("```\n`src/a.js`\n```") == set()

    def test_a_module_name_is_a_candidate_and_is_dropped_later(self):
        """`src.draw` looks like a path with an extension. It is cheaper to let it
        through here and find nothing than to teach this function the difference
        between a module and a file."""
        assert "src.draw" in cited_paths("Handled by `src.draw`.")
