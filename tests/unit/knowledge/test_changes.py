"""Reading a change from git: which files, which lines, what they say now."""

from __future__ import annotations

import subprocess

import pytest

from codelith.cli.commands import codebase_for_checkout
from codelith.knowledge.changes import ChangeError, ChangeSet, collect, overlaps


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("one = 1\ntwo = 2\nthree = 3\n")
    (tmp_path / "app" / "gone.py").write_text("x = 1\n")
    (tmp_path / "app" / "old.py").write_text("def f():\n    return 1\n" * 5)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


class TestTheWorkingCopy:
    def test_every_kind_of_change(self, repo) -> None:
        (repo / "app" / "a.py").write_text("one = 1\nTWO = 2\nthree = 3\n")
        (repo / "app" / "gone.py").unlink()
        git(repo, "mv", "app/old.py", "app/new.py")
        (repo / "app" / "fresh.py").write_text("print('hi')\nprint('there')\n")  # untracked

        change = collect(repo, "HEAD")
        by = {f.path: f for f in change.files}

        assert by["app/a.py"].status == "modified"
        assert by["app/a.py"].old_ranges == [(2, 2)] and by["app/a.py"].new_ranges == [(2, 2)]
        assert "TWO" in by["app/a.py"].content
        assert by["app/gone.py"].status == "deleted" and by["app/gone.py"].content is None
        assert by["app/new.py"].status == "renamed" and by["app/new.py"].old_path == "app/old.py"
        assert by["app/new.py"].before == "app/old.py"
        assert by["app/fresh.py"].status == "added"
        assert by["app/fresh.py"].new_ranges == [(1, 3)]

    def test_paths_are_relative_to_the_codebase_folder(self, repo) -> None:
        (repo / "app" / "a.py").write_text("changed\n")
        (repo / "outside.py").write_text("not part of app\n")
        change = collect(repo / "app", "HEAD")
        assert [f.path for f in change.files] == ["a.py"]

    def test_between_two_commits(self, repo) -> None:
        first = git(repo, "rev-parse", "HEAD")
        (repo / "app" / "a.py").write_text("one = 1\n")
        git(repo, "commit", "-qam", "trim")
        change = collect(repo, first, "HEAD")
        (only,) = change.files
        assert only.path == "app/a.py" and only.content == "one = 1\n"

    def test_an_unknown_base_says_what_to_do(self, repo) -> None:
        with pytest.raises(ChangeError, match="not a commit"):
            collect(repo, "0" * 40)

    def test_outside_a_repository(self, tmp_path) -> None:
        with pytest.raises(ChangeError, match="not inside a git repository"):
            collect(tmp_path, "HEAD")

    def test_it_travels_as_plain_data(self, repo) -> None:
        (repo / "app" / "a.py").write_text("x\n")
        change = collect(repo, "HEAD")
        again = ChangeSet.from_dict(change.to_dict())
        assert [(f.path, f.status, f.new_ranges) for f in again.files] == [
            (f.path, f.status, f.new_ranges) for f in change.files
        ]


def test_overlaps() -> None:
    assert overlaps([(5, 7)], 6, 10)
    assert overlaps([(5, 7)], 1, 5)
    assert not overlaps([(5, 7)], 8, 9)
    assert not overlaps([(5, 7)], None, None)


class TestWhichCodebaseACheckoutIs:
    def test_a_clone_of_a_github_repository_is_that_codebase(self, repo) -> None:
        git(repo, "remote", "add", "origin", "git@github.com:acme/shop.git")
        projects = [{"id": 9, "name": "shop", "sources": [{"source_type": "github", "url_or_path": "https://github.com/acme/shop", "branch": None}]}]
        found = codebase_for_checkout(projects, repo)
        assert found is not None and found[0]["id"] == 9 and found[1] == repo

    def test_the_folder_itself_wins(self, repo) -> None:
        projects = [{"id": 4, "name": "local", "sources": [{"source_type": "local", "url_or_path": str(repo), "branch": None}]}]
        assert codebase_for_checkout(projects, repo)[0]["id"] == 4

    def test_nothing_matches(self, repo) -> None:
        assert codebase_for_checkout([], repo) is None
