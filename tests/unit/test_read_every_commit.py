"""
Reading every commit from the command line: finding the codebase a source already has,
the rules `codelith watch` follows, and a git hook that never overwrites someone
else's.
"""

from __future__ import annotations

import subprocess

import pytest

from codelith.cli import build_parser
from codelith.cli.client import CliError
from codelith.cli.commands import HOOK_MARK, Watch, cmd_hook, describe_reuse, find_codebase
from codelith.cli.render import Output
from codelith.services.head_check import commits_between


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "one")
    return tmp_path


class TestFindingTheCodebase:
    def test_a_folder_is_found_however_it_is_spelled(self, tmp_path) -> None:
        projects = [{"id": 3, "sources": [{"source_type": "local", "url_or_path": str(tmp_path), "branch": None}]}]
        assert find_codebase(projects, "local", str(tmp_path / "." ), None)["id"] == 3

    @pytest.mark.parametrize(
        "spelling",
        ["https://github.com/acme/app", "https://github.com/acme/app.git", "github.com/acme/app/", "HTTPS://GitHub.com/acme/app"],
    )
    def test_a_url_is_found_however_it_is_spelled(self, spelling) -> None:
        projects = [{"id": 5, "sources": [{"source_type": "github", "url_or_path": "https://github.com/acme/app", "branch": None}]}]
        assert find_codebase(projects, "github", spelling, None)["id"] == 5

    def test_another_branch_is_another_codebase(self) -> None:
        projects = [{"id": 5, "sources": [{"source_type": "github", "url_or_path": "https://github.com/acme/app", "branch": "main"}]}]
        assert find_codebase(projects, "github", "https://github.com/acme/app", "dev") is None

    def test_the_new_commands_parse(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["watch"]).target == "."
        assert parser.parse_args(["hook", "install"]).action == "install"
        assert parser.parse_args(["analyse", ".", "--from-scratch"]).from_scratch is True


class FakeApi:
    def __init__(self, read_at: str | None, latest: str | None = None) -> None:
        self.read_at = read_at
        self.latest = latest
        self.started: list[int] = []
        self.jobs: dict[int, str] = {}

    def knowledge_base(self, _pid):
        return {"knowledge_base": {"commit_sha": self.read_at, "stats": {}}}

    def project(self, _pid):
        return {"latest_job": {"status": self.latest} if self.latest else None}

    def analyse(self, pid, force=False):
        job_id = len(self.started) + 1
        self.started.append(job_id)
        self.jobs[job_id] = "running"
        return {"id": job_id}

    def job(self, job_id):
        return {"status": self.jobs[job_id]}


class TestWatchRules:
    def watch(self, api) -> Watch:
        return Watch(api, {"id": 1, "name": "app"}, Output(as_json=True))

    def test_a_commit_already_read_starts_nothing(self) -> None:
        api = FakeApi(read_at="aaa")
        self.watch(api).step("aaa")
        assert api.started == []

    def test_a_new_commit_is_read_once(self) -> None:
        api = FakeApi(read_at="aaa")
        w = self.watch(api)
        w.step("bbb")
        w.step("bbb")
        assert api.started == [1]

    def test_commits_during_a_reading_cost_one_more_reading_not_one_each(self) -> None:
        api = FakeApi(read_at="aaa")
        w = self.watch(api)
        w.step("bbb")
        w.step("ccc")  # still reading bbb: wait
        w.step("ddd")
        assert api.started == [1]
        api.jobs[1] = "completed"
        api.read_at = "bbb"
        w.step("ddd")
        assert api.started == [1, 2]

    def test_a_reading_someone_else_started_is_waited_for(self) -> None:
        api = FakeApi(read_at="aaa", latest="running")
        self.watch(api).step("bbb")
        assert api.started == []


class TestTheHook:
    def args(self, action, target):
        return build_parser().parse_args(["hook", action, str(target)])

    def test_install_then_uninstall(self, repo) -> None:
        o = Output(as_json=True)
        assert cmd_hook(self.args("install", repo), o) == 0
        hook = repo / ".git" / "hooks" / "post-commit"
        text = hook.read_text()
        assert HOOK_MARK in text
        assert "analyse" in text and "--no-wait" in text
        assert cmd_hook(self.args("uninstall", repo), o) == 0
        assert not hook.exists()

    def test_someone_elses_hook_is_never_overwritten(self, repo) -> None:
        hook = repo / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\necho mine\n")
        with pytest.raises(CliError, match="did not write it"):
            cmd_hook(self.args("install", repo), Output(as_json=True))
        with pytest.raises(CliError, match="not written by Codelith"):
            cmd_hook(self.args("uninstall", repo), Output(as_json=True))
        assert hook.read_text() == "#!/bin/sh\necho mine\n"

    def test_outside_a_repository_it_says_so(self, tmp_path) -> None:
        with pytest.raises(CliError, match="not inside a git repository"):
            cmd_hook(self.args("install", tmp_path), Output(as_json=True))


class TestFreshness:
    def test_commits_between_counts_what_a_reading_has_not_seen(self, repo) -> None:
        first = git(repo, "rev-parse", "HEAD")
        for n in range(3):
            (repo / "a.py").write_text(f"x = {n + 2}\n")
            git(repo, "commit", "-q", "-am", f"c{n}")
        assert commits_between(str(repo), first, git(repo, "rev-parse", "HEAD")) == 3

    def test_an_unknown_commit_gives_no_count_rather_than_a_wrong_one(self, repo) -> None:
        assert commits_between(str(repo), "0" * 40, git(repo, "rev-parse", "HEAD")) is None

    def test_the_reuse_sentence(self) -> None:
        kb = {
            "knowledge_base": {
                "stats": {
                    "reuse": {
                        "from_kb": 4,
                        "files_changed": 2,
                        "files_added": 1,
                        "files_removed": 0,
                        "vectors_copied": 300,
                        "vectors_embedded": 9,
                        "summaries_kept": 40,
                        "summaries_written": 2,
                    }
                }
            }
        }
        sentence = describe_reuse(kb)
        assert sentence.startswith("3 files changed")
        assert "kept 300 vectors, embedded 9" in sentence
        assert "kept 40 summaries, wrote 2" in sentence
        assert describe_reuse({"knowledge_base": {"stats": {}}}) is None
