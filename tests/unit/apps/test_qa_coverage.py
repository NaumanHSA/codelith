"""
Which parts of the surface no test mentions.

Not line coverage. "84% covered" cannot be acted on — you cannot tell whether the
untested 16% is error handling or a `__repr__`. "Six of twenty-eight routes are named
in no test", with the six listed, can.

**The danger is that it looks like a measurement.** Name matching finds a route nobody
mentions reliably, and never finds a route exercised through a fixture. So the number
is a *floor on what is untested*, not a measure of what is tested, and every string
this module produces has to be readable that way. A number people trust that does not
mean what they think is worse than no number.
"""

from __future__ import annotations

import pytest

from codelith.apps.qa.coverage import CoverageReport, SurfaceItem, _is_test, _named_in, _needles


def _item(kind="route", name="GET /health") -> SurfaceItem:
    return SurfaceItem(kind=kind, name=name)


class TestWhatCountsAsNamed:
    def test_a_route_is_matched_by_its_path_not_its_verb(self) -> None:
        """No test contains the string "GET /health". They contain "/health"."""
        tests = {"tests/test_api.py": 'client.get("/health")'}

        assert _named_in(_item(), tests) == ("tests/test_api.py",)

    def test_a_route_nobody_mentions_is_uncovered(self) -> None:
        tests = {"tests/test_other.py": "assert 1 == 1"}

        assert _named_in(_item(), tests) == ()

    def test_a_cli_command_must_be_quoted(self) -> None:
        """The load-bearing case. Neurosurfer's CLI command is `neurosurfer`, which
        appears in every import line of every test — a bare substring search reported
        it covered by `tests/fakes.py`, which tests nothing of the sort. A test that
        invokes a command passes its name as a string."""
        imports_only = {"tests/fakes.py": "from neurosurfer.rag import Chunker"}
        invoked = {"tests/test_cli.py": 'run(["neurosurfer", "doctor"])'}

        assert _named_in(_item("cli_command", "neurosurfer"), imports_only) == ()
        assert _named_in(_item("cli_command", "neurosurfer"), invoked) == ("tests/test_cli.py",)

    def test_an_entrypoint_matches_its_module_path(self) -> None:
        tests = {"tests/test_main.py": "import neurosurfer.app.cli.app"}

        assert _named_in(_item("entrypoint", "neurosurfer/app/cli/app.py"), tests)

    def test_a_one_character_name_matches_nothing(self) -> None:
        """A short name matches everywhere, which reports everything covered — the
        most damaging direction for this number to be wrong in."""
        assert _needles(_item("route", "GET /")) == []
        assert _needles(_item("service", "X")) == []

    def test_every_matching_file_is_listed(self) -> None:
        """The list is the evidence. A count with nothing to check is a claim."""
        tests = {"a.py": '"/health"', "b.py": "get('/health')"}

        assert _named_in(_item(), tests) == ("a.py", "b.py")


class TestWhichFilesAreTests:
    @pytest.mark.parametrize(
        "path",
        [
            "tests/test_api.py",
            "test/foo.py",
            "src/__tests__/x.ts",
            "pkg/service_test.go",
            "src/app.test.ts",
            "src/app.spec.ts",
            "app/test_thing.py",
        ],
    )
    def test_recognised(self, path: str) -> None:
        assert _is_test(path)

    @pytest.mark.parametrize(
        "path",
        ["codelith/main.py", "src/testing_utils.py", "app/latest.py", "docs/protest.md"],
    )
    def test_not_a_test(self, path: str) -> None:
        """`latest.py` and `protest.md` contain "test". Substring matching on the whole
        path would count them, and every one inflates the covered side."""
        assert not _is_test(path)


class TestTheWording:
    def test_a_codebase_with_no_tests_is_told_so(self) -> None:
        """Otherwise it gets a list of twenty-eight failures, which is technically
        true and useless — the finding is "there are no tests", once."""
        report = CoverageReport(items=[_item()], no_tests_found=True)

        assert "No test files were found" in report.summary

    def test_nothing_to_check_is_not_a_pass(self) -> None:
        assert "No routes, commands or entry points" in CoverageReport().summary

    def test_the_summary_never_claims_coverage(self) -> None:
        """"Named in a test" is what was measured. "Covered" is what a reader would
        assume, and it is a stronger claim than name matching can support."""
        report = CoverageReport(items=[_item(), SurfaceItem("route", "GET /x", named_in=("t.py",))])

        assert "named in no test" in report.summary
        assert "covered" not in report.summary.lower()

    def test_all_named_says_so_without_overclaiming(self) -> None:
        report = CoverageReport(items=[SurfaceItem("route", "GET /x", named_in=("t.py",))])

        assert "named in a test" in report.summary
        assert "covered" not in report.summary.lower()

    def test_uncovered_lists_exactly_the_unnamed(self) -> None:
        named = SurfaceItem("route", "GET /a", named_in=("t.py",))
        unnamed = SurfaceItem("route", "GET /b")
        report = CoverageReport(items=[named, unnamed])

        assert report.uncovered == [unnamed]
