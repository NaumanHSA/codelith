"""
Reading what somebody else's tool said.

Two tools, two entirely different output formats, one `Finding`. Everything downstream
— ranking, impact, the UI — must not learn which tool produced a row, or adding a third
means touching all of it.

The cases here are the ones that break parsers in practice: output that is not what the
flag promised, a diagnostic split over two lines, and Windows paths.
"""

from __future__ import annotations

import pytest

from codelith.apps.qa.findings import Severity
from codelith.apps.qa.tools import MYPY, RUFF, parse_mypy, parse_ruff, tools_for


class TestRuff:
    def test_a_diagnostic_becomes_a_finding(self) -> None:
        out = """[
          {"code": "F401", "filename": "codelith/main.py",
           "location": {"row": 12, "column": 1},
           "message": "`os` imported but unused"}
        ]"""

        findings = parse_ruff(out, "")

        assert len(findings) == 1
        assert findings[0].rule == "F401"
        assert findings[0].path == "codelith/main.py"
        assert findings[0].line == 12
        assert findings[0].severity is Severity.WARNING

    def test_an_undefined_name_is_an_error(self) -> None:
        """`F821` is the one that broke every documentation job. A rule that fails at
        runtime is not the same as one that offends a style guide, and a reader who
        cannot tell them apart reads neither."""
        out = '[{"code": "F821", "filename": "a.py", "location": {"row": 1}, "message": "x"}]'

        assert parse_ruff(out, "")[0].severity is Severity.ERROR

    def test_a_syntax_error_is_an_error(self) -> None:
        out = '[{"code": "E902", "filename": "a.py", "location": {"row": 1}, "message": "x"}]'

        assert parse_ruff(out, "")[0].severity is Severity.ERROR

    def test_unparseable_output_yields_nothing_and_does_not_raise(self) -> None:
        """`--output-format json` is a promise, not a guarantee: a ruff that fails
        before it starts writes a plain-text error to stdout."""
        assert parse_ruff("error: invalid pyproject.toml", "") == []

    def test_empty_output_is_no_findings(self) -> None:
        assert parse_ruff("[]", "") == []
        assert parse_ruff("", "") == []

    def test_a_windows_path_is_normalised(self) -> None:
        """The knowledge base stores forward slashes, and every join in Q2 depends on
        the two matching."""
        out = '[{"code": "F401", "filename": "codelith\\\\main.py", "location": {"row": 1}, "message": "x"}]'

        assert parse_ruff(out, "")[0].path == "codelith/main.py"


class TestMypy:
    def test_an_error_line_becomes_a_finding(self) -> None:
        out = "codelith/db.py:40:12: error: Incompatible return value  [return-value]"

        findings = parse_mypy(out, "")

        assert len(findings) == 1
        assert findings[0].path == "codelith/db.py"
        assert findings[0].line == 40
        assert findings[0].column == 12
        assert findings[0].rule == "return-value"
        assert findings[0].severity is Severity.ERROR

    def test_a_line_without_a_column_still_parses(self) -> None:
        """`--show-column-numbers` is passed, but a mypy invoked another way — or an
        older one — omits it."""
        findings = parse_mypy("a.py:7: error: Bad thing  [assignment]", "")

        assert findings[0].line == 7
        assert findings[0].column == 0

    def test_a_note_is_not_a_finding(self) -> None:
        """Notes are continuations of the diagnostic above them. Counting them
        separately triples the number and buries the errors."""
        out = (
            "a.py:1: error: Argument 1 has incompatible type  [arg-type]\n"
            "a.py:1: note: Possible overload variant:\n"
            "a.py:1: note:     def f(x: int) -> None\n"
        )

        findings = parse_mypy(out, "")

        assert len(findings) == 1
        assert findings[0].severity is Severity.ERROR

    def test_a_missing_rule_still_parses(self) -> None:
        findings = parse_mypy("a.py:3: error: something went wrong", "")

        assert findings[0].rule == "type"

    def test_summary_and_noise_lines_are_ignored(self) -> None:
        out = "Found 3 errors in 2 files (checked 40 source files)\n\n"

        assert parse_mypy(out, "") == []


class TestWhichToolsApply:
    def test_python_gets_both(self) -> None:
        assert tools_for(["python"]) == [RUFF, MYPY]

    def test_an_unsupported_language_gets_nothing(self) -> None:
        """A Go repository run through ruff produces nothing, costs time, and reads to
        the user as "no problems found"."""
        assert tools_for(["go"]) == []

    def test_a_mixed_codebase_does_not_repeat_a_tool(self) -> None:
        assert tools_for(["python", "python", "typescript"]) == [RUFF, MYPY]

    def test_the_order_is_stable(self) -> None:
        """The report is rendered in this order, and a list that reshuffles between
        runs makes two reports impossible to compare."""
        assert tools_for(["python"]) == tools_for(["python"])

    @pytest.mark.parametrize("spec", [RUFF, MYPY])
    def test_every_spec_says_what_is_lost_without_it(self, spec) -> None:
        """A tool that is not installed is reported to the reader, and "ruff is
        missing" means nothing to somebody who does not know what ruff does."""
        assert spec.provides
        assert spec.command


class TestPathsMatchTheKnowledgeBase:
    """
    Ruff reports absolute paths even when invoked as `.`, and the knowledge base
    stores them relative to the repository root. Every join in Q2 matches on that
    string, so a mismatch produces a finding with no impact rather than an error —
    the failure is silent, which is why it is pinned here.
    """

    def test_the_checkout_root_is_stripped(self) -> None:
        from codelith.apps.qa.findings import Finding

        f = Finding(tool="ruff", rule="F401", path="/tmp/clone-abc/codelith/main.py", line=3)

        assert f.relative_to("/tmp/clone-abc").path == "codelith/main.py"

    def test_a_windows_root_matches_a_posix_path(self) -> None:
        """The clone path arrives with backslashes; findings are normalised to forward
        slashes before this runs."""
        from codelith.apps.qa.findings import Finding

        f = Finding(tool="ruff", rule="F401", path="D:/repos/x/codelith/main.py", line=3)

        assert f.relative_to(r"D:\repos\x").path == "codelith/main.py"

    def test_an_already_relative_path_is_left_alone(self) -> None:
        """Mypy reports relative paths, so the same code path sees both."""
        from codelith.apps.qa.findings import Finding

        f = Finding(tool="mypy", rule="type", path="codelith/db.py", line=1)

        assert f.relative_to("/tmp/clone-abc").path == "codelith/db.py"

    def test_an_unrelated_absolute_path_is_not_mangled(self) -> None:
        from codelith.apps.qa.findings import Finding

        f = Finding(tool="ruff", rule="F401", path="/elsewhere/a.py", line=1)

        assert f.relative_to("/tmp/clone-abc").path == "/elsewhere/a.py"


class TestNoiseIsExcluded:
    def test_runtime_directories_are_skipped(self) -> None:
        """Codelith keeps `repos/` and `runs/` for clones and job artifacts. Mypy
        walking into them found four copies of the same analysed project and gave up
        with "duplicate module" — 0 findings, exit 2, and a report that read clean."""
        from codelith.apps.qa.tools import MYPY, RUFF

        assert "repos" in RUFF.command
        assert "runs" in RUFF.command
        assert "repos" in MYPY.command[-1]
        assert "node_modules" in MYPY.command[-1]
