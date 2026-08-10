"""
Writing a test for something no test names — and checking it before anybody runs it.

**Nothing is executed.** Running generated code against somebody's repository needs a
sandbox, and that is the point at which Codelith stops being read-only about their
machine. A decision to take deliberately, not to arrive at because generation felt
incomplete.

**A test that imports a module which does not exist is worse than no test.** It fails
on the first run and the reader concludes the feature is broken rather than that the
guess was — so imports are checked against the knowledge base, the same rule citations
follow.
"""

from __future__ import annotations

import pytest

from codelith.apps.qa.coverage import SurfaceItem
from codelith.apps.qa.testgen import GeneratedTest, GenerationReport, _check_imports, _extract_code, _suggest_path


class TestExtractingTheCode:
    def test_a_fenced_block_is_taken(self) -> None:
        raw = "Here is the test:\n\n```python\nimport pytest\n\ndef test_x(): ...\n```\n"

        assert _extract_code(raw).startswith("import pytest")
        assert "Here is the test" not in _extract_code(raw)

    def test_prose_outside_the_fence_is_dropped(self) -> None:
        """A model that explains itself first would otherwise put English at the top
        of a `.py` file, which fails to import before any assertion runs."""
        raw = "I'll test the route.\n```python\nx = 1\n```\nLet me know if you want more."

        assert _extract_code(raw) == "x = 1"

    def test_an_unfenced_response_is_used_whole(self) -> None:
        assert _extract_code("import pytest\ndef test_x(): ...") .startswith("import pytest")

    def test_an_empty_response_is_empty(self) -> None:
        assert _extract_code("") == ""


class TestCheckingImports:
    def test_a_known_module_resolves(self) -> None:
        resolved, unresolved = _check_imports(
            "from neurosurfer.app.server import gateway", {"neurosurfer.app.server"}
        )

        assert resolved == ("neurosurfer.app.server",)
        assert unresolved == ()

    def test_an_invented_module_is_reported(self) -> None:
        """The load-bearing case. A plausible-looking import the analysis has never
        seen means the test will not run."""
        _, unresolved = _check_imports(
            "from neurosurfer.does.not.exist import Thing", {"neurosurfer.app"}
        )

        assert unresolved == ("neurosurfer.does.not.exist",)

    def test_third_party_and_stdlib_are_not_judged(self) -> None:
        """`pytest` and `httpx` are not in the knowledge base and never will be.
        Reporting them would make every generated test look broken."""
        resolved, unresolved = _check_imports(
            "import pytest\nimport os\nfrom httpx import Client\n", {"neurosurfer.app"}
        )

        assert resolved == () and unresolved == ()

    def test_a_prefix_of_a_known_module_resolves(self) -> None:
        """Importing the package when the analysis recorded its submodule is correct."""
        resolved, _ = _check_imports("import neurosurfer.app", {"neurosurfer.app.server"})

        assert resolved == ("neurosurfer.app",)

    def test_each_module_is_reported_once(self) -> None:
        resolved, _ = _check_imports(
            "from a.b import x\nfrom a.b import y\n", {"a.b"}
        )

        assert resolved == ("a.b",)


class TestSayingSoBeforeItIsRun:
    def test_an_ungrounded_test_carries_a_warning(self) -> None:
        test = GeneratedTest(
            target="GET /", suggested_path="tests/test_x.py", code="",
            unresolved_imports=("a.b",),
        )

        assert not test.grounded
        assert "has not seen" in test.warning

    def test_a_grounded_test_says_nothing(self) -> None:
        test = GeneratedTest(target="GET /", suggested_path="p", code="", resolved_imports=("a",))

        assert test.grounded
        assert test.warning == ""

    def test_the_summary_always_says_nothing_was_run(self) -> None:
        """The one thing a reader must not assume. A generated test that looks like a
        passing test is a lie about the state of the codebase."""
        report = GenerationReport(tests=[GeneratedTest("t", "p", "code")])

        assert "None has been run" in report.summary

    def test_ungrounded_tests_are_counted_in_the_summary(self) -> None:
        report = GenerationReport(
            tests=[GeneratedTest("t", "p", "c", unresolved_imports=("x",))]
        )

        assert "1 with imports to check" in report.summary


class TestTheSuggestedPath:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("GET /v1/models", "tests/test_get_v1_models.py"),
            ("neurosurfer", "tests/test_neurosurfer.py"),
        ],
    )
    def test_a_name_becomes_a_filename(self, name: str, expected: str) -> None:
        assert _suggest_path(SurfaceItem("route", name)) == expected

    def test_a_name_with_nothing_usable_still_gives_a_path(self) -> None:
        assert _suggest_path(SurfaceItem("route", "///")) == "tests/test_surface.py"
