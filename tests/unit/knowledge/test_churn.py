"""
How often each file changed, read from git. Parsing is tested on a string; reading is
tested on a real repository made in a temporary folder, with commit dates set so the
recent window is known.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from codelith.knowledge.churn import Churn, parse_log, read

DAY = 86400


class TestParsing:
    def test_commits_are_counted_per_file_in_both_windows(self) -> None:
        now = 1_800_000_000
        log = (
            f"\x00{now - 1 * DAY}\n\na.py\nb.py\n"
            f"\x00{now - 10 * DAY}\n\na.py\n"
            f"\x00{now - 200 * DAY}\n\na.py\nc.py\n"
        )
        churn = parse_log(log, now, days=90)
        assert churn.total == {"a.py": 3, "b.py": 1, "c.py": 1}
        assert churn.recent == {"a.py": 2, "b.py": 1}
        assert (churn.commits, churn.recent_commits) == (3, 2)
        assert churn.since is not None

    def test_a_file_listed_twice_in_one_commit_counts_once(self) -> None:
        churn = parse_log("\x001000\n\na.py\na.py\n", 1000)
        assert churn.total == {"a.py": 1}

    def test_it_round_trips_through_json(self) -> None:
        churn = parse_log("\x001000\n\na.py\n", 1000)
        again = Churn.from_json(churn.to_json())
        assert again is not None and again.total == churn.total and again.commits == 1

    def test_nothing_stored_is_no_history(self) -> None:
        assert Churn.from_json({}) is None
        assert Churn.from_json(None) is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
class TestReadingARepository:
    @staticmethod
    def _commit(root: Path, files: dict[str, str], days_ago: int, message: str) -> None:
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        when = f"{int(time.time()) - days_ago * DAY} +0000"
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_DATE": when,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env, capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True, env=env, capture_output=True)

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
        self._commit(tmp_path, {"app/core.py": "1", "app/old.py": "1"}, 300, "start")
        self._commit(tmp_path, {"app/core.py": "2"}, 20, "two")
        self._commit(tmp_path, {"app/core.py": "3", "app/new.py": "1"}, 2, "three")
        return tmp_path

    def test_it_counts_recent_and_total(self, repo: Path) -> None:
        churn = read(repo, deepen=False)
        assert churn is not None and not churn.shallow
        assert churn.total == {"app/core.py": 3, "app/old.py": 1, "app/new.py": 1}
        assert churn.recent == {"app/core.py": 2, "app/new.py": 1}
        assert (churn.commits, churn.recent_commits) == (3, 2)

    def test_it_keeps_to_the_files_of_the_reading(self, repo: Path) -> None:
        churn = read(repo, {"app/core.py"}, deepen=False)
        assert churn is not None and set(churn.total) == {"app/core.py"}

    def test_paths_are_relative_to_a_folder_inside_the_repository(self, repo: Path) -> None:
        churn = read(repo / "app", deepen=False)
        assert churn is not None and churn.total.get("core.py") == 3

    def test_it_reads_up_to_an_older_commit(self, repo: Path) -> None:
        churn = read(repo, deepen=False, rev="HEAD~1")
        assert churn is not None and churn.total == {"app/core.py": 2, "app/old.py": 1}

    def test_a_folder_that_is_not_a_repository_has_no_history(self, tmp_path: Path, monkeypatch) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        # Never look above the temporary folder, wherever it happens to live.
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        assert read(plain, deepen=False) is None
