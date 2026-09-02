"""
Whether analysing again would read anything new.

Analysis is the expensive thing this product does, and the button that starts it said
nothing about what it would achieve. Re-analysing a repository that has not moved costs
exactly as much as re-analysing one that has, stores the same knowledge base — the same
commit upserts — and does not even give drift a second point to compare.

The rule that shapes every case below: **this informs a decision, it never gates one.**
A check that cannot reach the remote must not stand between an operator and the run
they asked for, so every failure resolves to "could not tell, go ahead" rather than to
a refusal.
"""

from __future__ import annotations

import pytest

from codelith.services import head_check as hc

SHA_OLD = "8f673f64b089a8caa3db5f2b1453607203b31f0e"
SHA_NEW = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


async def _check(monkeypatch, current, analysed=SHA_OLD, source_type="github"):
    """Run the check with `_current_head` stubbed — the git call is not what is
    being tested, the decision made from its answer is."""
    monkeypatch.setattr(hc, "_current_head", lambda *a, **k: current)
    return await hc.head_check(
        source_type=source_type,
        url_or_path="https://example.com/repo.git",
        branch=None,
        analysed_commit=analysed,
    )


class TestTheAnswer:
    async def test_an_unmoved_repository_is_reported_as_unchanged(self, monkeypatch) -> None:
        check = await _check(monkeypatch, SHA_OLD)

        assert check.checked is True
        assert check.changed is False
        assert "same commit" in check.summary()

    async def test_the_summary_says_why_it_matters(self, monkeypatch) -> None:
        """
        "Nothing changed" on its own reads as trivia. The reason to care is that the
        run costs the same and leaves you with one reading rather than two.
        """
        check = await _check(monkeypatch, SHA_OLD)

        assert "drift" in check.summary()

    async def test_a_moved_repository_shows_both_commits(self, monkeypatch) -> None:
        check = await _check(monkeypatch, SHA_NEW)

        assert check.changed is True
        assert check.short_analysed in check.summary()
        assert check.short_current in check.summary()

    async def test_a_project_never_analysed_is_not_a_re_analysis(self, monkeypatch) -> None:
        """
        There is nothing to compare against and nothing to warn about — the dialog
        should offer the run, not argue with it.
        """
        check = await _check(monkeypatch, SHA_NEW, analysed=None)

        assert check.never_analysed is True
        assert check.changed is True
        assert "has not been read yet" in check.summary()

    async def test_it_does_not_call_out_to_answer_that(self, monkeypatch) -> None:
        """A project with no reading needs no network round trip to classify."""
        called: list[bool] = []
        monkeypatch.setattr(hc, "_current_head", lambda *a, **k: called.append(True) or SHA_NEW)

        await hc.head_check(
            source_type="github", url_or_path="x", branch=None, analysed_commit=None
        )

        assert called == []


class TestItNeverBlocksTheRun:
    async def test_an_unreachable_remote_is_a_caveat_not_a_refusal(
        self, monkeypatch
    ) -> None:
        check = await _check(monkeypatch, RuntimeError("Could not reach the remote."))

        assert check.checked is False
        assert check.changed is True, "unknown must not read as 'nothing to do'"
        assert check.reason == "Could not reach the remote."

    async def test_a_timeout_is_the_same(self, monkeypatch) -> None:
        async def _never(*_a, **_k):
            raise TimeoutError

        monkeypatch.setattr(hc.asyncio, "wait_for", _never)
        check = await _check(monkeypatch, SHA_NEW)

        assert (check.checked, check.changed) == (False, True)
        assert "seconds" in (check.reason or "")

    async def test_an_unexpected_failure_is_still_not_a_refusal(self, monkeypatch) -> None:
        def _explode(*_a, **_k):
            raise ValueError("something nobody predicted")

        monkeypatch.setattr(hc, "_current_head", _explode)
        check = await hc.head_check(
            source_type="github", url_or_path="x", branch=None, analysed_commit=SHA_OLD
        )

        assert (check.checked, check.changed) == (False, True)

    async def test_the_unknown_summary_does_not_pretend_to_know(self, monkeypatch) -> None:
        check = await _check(monkeypatch, RuntimeError("no network"))

        assert "Could not tell" in check.summary()


class TestTheFailureIsSaidInWordsAnOperatorCanAct:
    """A git stack trace is not a thing anybody can do something about."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("fatal: Authentication failed for 'https://…'", "credentials"),
            ("remote: Repository not found", "could not find"),
            ("fatal: unable to access: Could not resolve host: github.com", "Could not reach"),
        ],
    )
    def test_common_git_failures_are_translated(self, raw: str, expected: str) -> None:
        assert expected in hc._humanise(Exception(raw), "github", "https://x/y.git")

    def test_a_local_path_without_git_says_so(self) -> None:
        message = hc._humanise(Exception("not a git repository"), "local", "/tmp/x")

        assert "not a git repository" in message
