"""
The half no linter can produce.

Ruff found the `F821` that broke composition; what it could not say is that the method
runs inside the documentation workflow and three written pages cite the file. This is
where that sentence comes from, and where the ordering that puts it first is decided.

**Ranking is the product.** A repository returns hundreds of findings — Codelith's own
returns two thousand — and nobody reads a list of hundreds. If the first ten rows are
not the ten worth reading, the app is a slower way to run ruff.
"""

from __future__ import annotations

import pytest

from codelith.apps.qa.findings import Finding, Impact, Severity
from codelith.apps.qa.impact import ImpactResolver


def _resolver() -> ImpactResolver:
    return ImpactResolver(db=None, project_id=1, kb_id=1)  # type: ignore[arg-type]


def _finding(path="a.py", line=10, severity=Severity.WARNING, rule="X") -> Finding:
    return Finding(tool="ruff", rule=rule, path=path, line=line, severity=severity)


class TestRanking:
    def test_severity_dominates_reach(self) -> None:
        """An undefined name is not a style preference. A widely-imported style nit
        must not outrank a runtime error in a corner."""
        r = _resolver()
        error = _finding(severity=Severity.ERROR).with_impact(Impact(reached_files=0))
        nit = _finding(severity=Severity.WARNING).with_impact(Impact(reached_files=200))

        assert sorted([nit, error], key=r.rank)[0] is error

    def test_reach_breaks_ties_within_a_severity(self) -> None:
        r = _resolver()
        far = _finding(path="core.py").with_impact(Impact(reached_files=30))
        near = _finding(path="leaf.py").with_impact(Impact(reached_files=0))

        assert sorted([near, far], key=r.rank)[0] is far

    def test_documentation_counts_for_more_than_one_importer(self) -> None:
        """A written page citing the file means the bug is already published. That is
        worth more than one more module importing it."""
        r = _resolver()
        documented = _finding(path="a.py").with_impact(
            Impact(reached_files=1, documented_in=("Architecture",))
        )
        imported = _finding(path="b.py").with_impact(Impact(reached_files=4))

        assert sorted([imported, documented], key=r.rank)[0] is documented

    def test_reach_is_capped(self) -> None:
        """A file 200 modules import is not twice as urgent as one 100 import — both
        mean load-bearing. Without a ceiling the single most-imported file crowds out
        every other error."""
        r = _resolver()
        huge = _finding(path="a.py", severity=Severity.ERROR).with_impact(Impact(reached_files=5000))
        big = _finding(path="b.py", severity=Severity.ERROR).with_impact(Impact(reached_files=40))

        assert r.rank(huge)[1] == r.rank(big)[1]

    def test_a_finding_without_impact_still_ranks(self) -> None:
        """The graph is optional infrastructure. If it is down every finding loses a
        column — none may lose its place in the list."""
        r = _resolver()

        assert r.rank(_finding()) is not None

    def test_the_order_is_deterministic(self) -> None:
        """Two runs that disagree about order cannot be compared, and comparing runs
        is how somebody sees whether they are winning."""
        r = _resolver()
        rows = [_finding(path=p) for p in ("c.py", "a.py", "b.py")]

        assert [f.path for f in sorted(rows, key=r.rank)] == ["a.py", "b.py", "c.py"]


class TestTheSentence:
    def test_it_names_symbol_reach_and_documentation(self) -> None:
        r = _resolver()
        f = _finding().with_impact(
            Impact(reached_files=34, symbol="DiagramAgent.run", documented_in=("API",))
        )

        text = r.explain(f)

        assert "DiagramAgent.run" in text
        assert "34 files reach it" in text
        assert "1 written page cite" in text

    def test_nothing_true_to_say_says_nothing(self) -> None:
        """"This affects 0 files" is noise, and a column full of it teaches people to
        skip the column."""
        r = _resolver()

        assert r.explain(_finding()) == ""
        assert r.explain(_finding().with_impact(Impact())) == ""

    def test_singular_and_plural_are_both_right(self) -> None:
        r = _resolver()
        one = _finding().with_impact(Impact(reached_files=1))

        assert "1 file reach" in r.explain(one)
        assert "files" not in r.explain(one)


class TestTheEnclosingSymbol:
    def test_the_last_symbol_starting_before_the_line_wins(self) -> None:
        """The knowledge base records where a symbol starts, not where it ends."""
        r = _resolver()
        r._symbols = {"a.py": [(10, "first"), (40, "second"), (80, "third")]}

        assert r._symbol_at("a.py", 55) == "second"

    def test_a_line_above_the_first_symbol_has_none(self) -> None:
        """Module-level code — imports, constants — is not inside anything. Guessing
        the file's first function would attribute an import error to a function that
        does not contain it."""
        r = _resolver()
        r._symbols = {"a.py": [(10, "first")]}

        assert r._symbol_at("a.py", 3) is None

    def test_an_unknown_file_has_none(self) -> None:
        assert _resolver()._symbol_at("never-analysed.py", 5) is None


class TestSymbolAttributionIsHonest:
    """
    The knowledge base stores symbols per *module*, and a module is usually several
    files — so a symbol at line 47 could belong to any of them. Attributing anyway
    would place a finding inside a function from a different file, and a reader cannot
    tell a confident wrong answer from a right one.
    """

    def test_a_multi_file_module_is_not_attributed(self) -> None:
        import asyncio
        from types import SimpleNamespace

        r = _resolver()

        class _Repos:
            class modules:
                @staticmethod
                async def list_by_kb(*a, **k):
                    return [
                        SimpleNamespace(
                            files_json=["a.py", "b.py"],
                            symbols_json=[{"name": "f", "line": 10}],
                        )
                    ]

        import codelith.apps.qa.impact as impact_mod

        original = impact_mod.KnowledgeRepositories
        impact_mod.KnowledgeRepositories = SimpleNamespace(for_session=lambda db: _Repos())
        try:
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                r._load_symbols({"a.py"})
            )
        finally:
            impact_mod.KnowledgeRepositories = original

        assert r._symbol_at("a.py", 20) is None, "a guess would be worse than nothing"

    def test_a_method_carries_its_class(self) -> None:
        """`run` says nothing; `DiagramAgent.run` says where to look."""
        r = _resolver()
        r._symbols = {"a.py": [(10, "DiagramAgent.run")]}

        assert r._symbol_at("a.py", 12) == "DiagramAgent.run"
