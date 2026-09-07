"""
Modules, as an explorer rather than a radar.

Unlike the architecture map this reads columns analysis wrote directly, so there is
little to coerce. What there is to get right is the ordering, the counting of what
was not written, and the decision that test modules come back at all.

That last one is the one worth a test: `list_by_kb` excludes tests by default because
its callers build prompts, and taking that default here would silently drop five
files and 591 lines from a page whose job is to say what is in the repository.
"""

from __future__ import annotations

import pytest

from codelith.services.module_service import assemble

#: "Not supplied", so that passing an explicit None is a case the test can express.
#: Without it `files=None` and `files` omitted are the same call, and the parametrised
#: junk test silently checked the default instead of the null column it names.
UNSET = object()


class Row:
    """A `KBModule` reduced to the columns the assembly reads."""

    def __init__(
        self,
        name: str,
        *,
        path: str | None = None,
        loc: int = 0,
        role: str = "service",
        kind: str = "package",
        language: str | None = "python",
        file_count: int = 1,
        is_test: bool = False,
        summary: str | None = "Some prose.",
        files: object = UNSET,
        symbols: object = UNSET,
    ):
        self.name = name
        self.path = path or name.replace(".", "/")
        self.loc = loc
        self.role = role
        self.kind = kind
        self.language = language
        self.file_count = file_count
        self.is_test = is_test
        self.summary = summary
        self.files_json = [f"{self.path}/a.py"] if files is UNSET else files
        self.symbols_json = [] if symbols is UNSET else symbols


class TestOrdering:
    def test_largest_first(self):
        """Size is the closest thing to importance knowable without reading."""
        out = assemble([Row("small", loc=10), Row("big", loc=900), Row("mid", loc=100)], "abc")
        assert [m.name for m in out.modules] == ["big", "mid", "small"]

    def test_ties_break_by_name_so_the_order_is_stable(self):
        out = assemble([Row("zeta", loc=5), Row("alpha", loc=5)], "abc")
        assert [m.name for m in out.modules] == ["alpha", "zeta"]

    def test_nothing_analysed(self):
        out = assemble([], None)
        assert out.available is False and out.modules == []


class TestTestModules:
    def test_they_are_returned(self):
        """
        The decision this file exists to hold. Taking `list_by_kb`'s default would
        drop the test suite from a page whose job is to say what is in the
        repository.
        """
        out = assemble([Row("tests", loc=591, role="test", is_test=True, summary=None)], "abc")
        assert [m.name for m in out.modules] == ["tests"]
        assert out.modules[0].is_test is True

    def test_an_unsummarised_test_module_is_not_counted_as_a_gap(self):
        """Test modules are deliberately not summarised. Counting them would report
        a decision as a defect."""
        out = assemble(
            [
                Row("tests", role="test", is_test=True, summary=None),
                Row("src", summary=None),
            ],
            "abc",
        )
        assert out.without_summary == 1

    def test_their_lines_count_towards_the_total(self):
        out = assemble([Row("src", loc=100), Row("tests", loc=591, is_test=True)], "abc")
        assert out.total_loc == 691


class TestWhatEachRowCarries:
    def test_the_summary_that_has_never_been_on_screen(self):
        out = assemble([Row("src", summary="  This module handles capture.  ")], "abc")
        assert out.modules[0].summary == "This module handles capture."

    def test_files_travel_with_the_module(self):
        """Without them a module is another paragraph to take on trust; with them it
        opens in the code viewer."""
        out = assemble([Row("src", files=["src/a.js", "src/b.js"])], "abc")
        assert out.modules[0].files == ["src/a.js", "src/b.js"]

    def test_symbols_are_counted_not_carried(self):
        out = assemble([Row("src", symbols=[{"name": "a"}, {"name": "b"}])], "abc")
        assert out.modules[0].symbols == 2

    @pytest.mark.parametrize("junk", [None, "a string", 42, {}])
    def test_a_files_column_of_the_wrong_shape_costs_the_files_not_the_page(self, junk):
        out = assemble([Row("src", files=junk, symbols=junk)], "abc")
        assert out.available and out.modules[0].files == [] and out.modules[0].symbols == 0

    def test_non_string_entries_in_the_file_list_are_dropped(self):
        out = assemble([Row("src", files=["src/a.js", None, 7, ""])], "abc")
        assert out.modules[0].files == ["src/a.js"]

    def test_a_null_language_is_empty_not_none(self):
        """Mixed-language modules store null, and the table renders a string."""
        out = assemble([Row("src", language=None)], "abc")
        assert out.modules[0].language == ""

    def test_a_very_long_file_list_is_bounded(self):
        out = assemble([Row("big", files=[f"f{i}.py" for i in range(900)])], "abc")
        assert len(out.modules[0].files) == 400

    def test_the_commit_travels_with_the_answer(self):
        assert assemble([Row("src")], "8f673f6").commit_sha == "8f673f6"
