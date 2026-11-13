"""Analyse without force keeps the last reading only while the code has not moved."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.services.head_check import HeadCheck
from codelith.workers.tasks import analysis_tasks

PROJECT = SimpleNamespace(
    sources=[SimpleNamespace(source_type="local", url_or_path="/repo", branch=None)]
)


def answer(**kwargs):
    async def check(**_):
        return HeadCheck(never_analysed=False, **kwargs)

    return check


@pytest.mark.parametrize(
    ("result", "moved"),
    [
        ({"checked": True, "changed": False}, False),  # same commit: keep the reading
        ({"checked": True, "changed": True}, True),  # new commit: read again
        ({"checked": False, "changed": True}, True),  # could not tell: read again
    ],
)
async def test_code_moved(monkeypatch, result, moved) -> None:
    monkeypatch.setattr("codelith.services.head_check.head_check", answer(**result))
    assert await analysis_tasks._code_moved(PROJECT, "abc") is moved


async def test_no_source_or_no_commit_counts_as_moved() -> None:
    assert await analysis_tasks._code_moved(SimpleNamespace(sources=[]), "abc") is True
    assert await analysis_tasks._code_moved(PROJECT, None) is True
