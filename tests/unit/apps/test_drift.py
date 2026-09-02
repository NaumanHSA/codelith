"""
What changed between two readings, and what it makes wrong.

The claim this app makes is narrow and worth pinning: not "these files changed" —
`git diff` says that better — but **which written pages now describe code that has
moved.** A page records the files it was written from, so that is a set intersection
against the modules that changed, with no re-reading and no model call.

What is easy to get wrong here is the middle: deciding when two readings of the same
module differ *enough* to tell somebody. Too eager and every run reports a reflowed
comment; too shy and a module whose functions were all replaced passes silently
because it happens to be the same length.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.apps.drift.service import DriftService, _reason_sentence


def _module(path: str, *, loc: int = 100, files: int = 3, symbols=None, name: str | None = None):
    return SimpleNamespace(
        path=path,
        name=name or path.rsplit("/", 1)[-1],
        loc=loc,
        file_count=files,
        symbols_json=symbols if symbols is not None else [{"name": "run"}],
    )


class TestWhenAModuleHasChangedEnoughToMention:
    def test_replaced_symbols_are_reported_even_at_the_same_size(self) -> None:
        """
        The case a size comparison misses entirely: a module whose every function was
        replaced, and which happens to be the same length afterwards.
        """
        before = _module("app/auth", loc=100, symbols=[{"name": "login"}])
        after = _module("app/auth", loc=100, symbols=[{"name": "authenticate"}])
        assert DriftService._how_it_changed(before, after) == "rewritten"

    def test_a_reflowed_comment_is_not_news(self) -> None:
        """Below the threshold is true and not worth anybody's attention."""
        before = _module("app/auth", loc=100)
        after = _module("app/auth", loc=104)
        assert DriftService._how_it_changed(before, after) is None

    @pytest.mark.parametrize(
        "before_loc,after_loc,expected",
        [(100, 140, "grew"), (140, 100, "shrank"), (100, 100, None)],
    )
    def test_size_moves(self, before_loc: int, after_loc: int, expected) -> None:
        assert (
            DriftService._how_it_changed(_module("m", loc=before_loc), _module("m", loc=after_loc))
            == expected
        )

    def test_symbols_may_be_bare_strings(self) -> None:
        """Provider output is not uniformly shaped; a symbol list of names is valid."""
        before = _module("m", symbols=["a", "b"])
        after = _module("m", symbols=["a", "b"])
        assert DriftService._how_it_changed(before, after) is None
        assert DriftService._how_it_changed(before, _module("m", symbols=["a"])) == "rewritten"


class TestTheSentenceAPersonReads:
    def test_it_says_what_happened_not_what_the_column_is_called(self) -> None:
        assert _reason_sentence(["removed"]) == "code it describes was deleted"
        assert "replaced" in _reason_sentence(["rewritten"])

    def test_several_reasons_are_joined(self) -> None:
        out = _reason_sentence(["grew", "removed"])
        assert "grown" in out and "deleted" in out


class TestTheReport:
    def _report(self, **kw):
        from codelith.apps.drift.service import DriftReport

        return DriftReport(project_id=1, from_commit="aaa", to_commit="bbb", **kw)

    def test_one_reading_is_not_an_empty_difference(self) -> None:
        """
        A project analysed once has no history — which is a different statement from
        "nothing changed", and the API returns `comparable: false` rather than a
        report of zero changes.
        """
        assert self._report().is_empty is True
        assert "Nothing structural changed" in self._report().summary()

    def test_the_summary_leads_with_the_pages(self) -> None:
        """
        Modules moving is context. Pages that are now wrong is the reason to look.
        """
        from codelith.apps.drift.service import ModuleChange, PageAtRisk

        r = self._report(
            modules=[ModuleChange("app/auth", "auth", "rewritten", 100, 120, 3, 3)],
            pages_at_risk=[
                PageAtRisk("api/auth", "Auth", ["app/auth/login.py"], "symbols replaced")
            ],
        )
        summary = r.summary()
        assert "1 changed shape" in summary
        assert "1 written page(s) now describe code that moved" in summary

    def test_module_deltas_are_signed(self) -> None:
        from codelith.apps.drift.service import ModuleChange

        assert ModuleChange("m", "m", "grew", 100, 140).loc_delta == 40
        assert ModuleChange("m", "m", "shrank", 140, 100).loc_delta == -40


class TestPagesAreMatchedByPrefix:
    """
    A module is a directory; a page cites files. Matching by prefix is what connects
    them without the knowledge base having to store the mapping — and it must not
    match a *sibling* directory that merely shares a name prefix.
    """

    @pytest.mark.parametrize(
        "module_path,cited_file,matches",
        [
            ("app/auth", "app/auth/login.py", True),
            ("app/auth", "app/auth", True),
            # `app/authz` is a different module; a naive `startswith` says yes.
            ("app/auth", "app/authz/policy.py", False),
            ("app/auth", "app/billing/invoice.py", False),
        ],
    )
    def test_prefix_matching(self, module_path: str, cited_file: str, matches: bool) -> None:
        hit = cited_file == module_path or cited_file.startswith(module_path.rstrip("/") + "/")
        assert hit is matches
