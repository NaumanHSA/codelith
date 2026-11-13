"""
A codebase's history (`knowledge/history.py`): commits read from a real git repository,
the commits between two readings, each reading against the one before, one file's own
history, and how much of it is kept.
"""

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from codelith.db.repositories.knowledge.commit_repo import CommitRepository
from codelith.db.repositories.knowledge.source_repo import SnapshotFile, SourceRepository
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.history import HistoryService, between, read_commits
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project, ProjectSource
from codelith.models.source import SourceBlob, SourceCommit


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Ada", "-c", "user.email=ada@example.com", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path) -> tuple[Path, list[str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    shas = [
        _commit(repo, {"app/a.py": "x = 1\n", "README.md": "hi\n"}, "Start"),
        _commit(repo, {"docs/guide.md": "guide\n"}, "Docs only, outside app/"),
        _commit(repo, {"app/a.py": "x = 2\n", "app/b.py": "y = 1\n"}, "Change a, add b"),
    ]
    return repo, shas


class TestReadingGit:
    def test_commits_newest_first_with_files_and_no_email(self, repo) -> None:
        path, shas = repo
        commits = read_commits(path)
        assert [c.sha for c in commits] == list(reversed(shas))
        assert commits[0].subject == "Change a, add b" and commits[0].author == "Ada"
        assert set(commits[0].files) == {"app/a.py", "app/b.py"}
        assert commits[0].parents == (shas[1],) and commits[0].when is not None
        assert not any("example.com" in repr(c) for c in commits)

    def test_a_codebase_in_a_folder_gets_its_own_history_linked_up(self, repo) -> None:
        path, shas = repo
        commits = read_commits(path / "app")
        assert [c.subject for c in commits] == ["Change a, add b", "Start"]
        assert commits[0].parents == (shas[0],), "the docs commit is skipped and the parent rewritten past it"
        assert set(commits[0].files) == {"a.py", "b.py"}

    def test_not_a_repository(self, tmp_path) -> None:
        assert read_commits(tmp_path) is None


def _c(sha: str, parents: list[str], day: int) -> SourceCommit:
    return SourceCommit(project_id=0, sha=sha, parents_json=parents, author="A", subject=sha,
                        authored_at=datetime(2026, 11, day, tzinfo=UTC), files_json=[])


class TestBetween:
    #   a - b - c ----- m (merge) - e
    #        \- d1 - d2 /
    KEPT = [_c("a", [], 1), _c("b", ["a"], 2), _c("c", ["b"], 3), _c("d1", ["b"], 4), _c("d2", ["d1"], 5),
            _c("m", ["c", "d2"], 6), _c("e", ["m"], 7)]

    def test_what_git_would_list(self) -> None:
        found = between(self.KEPT, "c", "e")
        assert [c.sha for c in found.commits] == ["e", "m", "d2", "d1"]
        assert found.complete and found.known

    def test_a_reading_older_than_what_is_kept(self) -> None:
        found = between(self.KEPT[2:], "a", "e")
        assert not found.complete and "fetch the history" in found.reason

    def test_nothing_kept_for_the_later_reading(self) -> None:
        assert not between(self.KEPT, "a", "zzz").known


@pytest_asyncio.fixture
async def project(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-hi-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-hi-{tag}")
    db_session.add(project)
    await db_session.flush()
    return project


async def _reading(db, project, sha: str, files: dict[str, str] | None, when: datetime) -> KnowledgeBase:
    kb = KnowledgeBase(project_id=project.id, commit_sha=sha, status=KBStatus.READY, created_at=when)
    db.add(kb)
    await db.flush()
    if files is not None:
        await SourceRepository(db).store(kb.id, [SnapshotFile(path=p, content=c, language="python") for p, c in files.items()])
    return kb


class TestReadingsOneAfterAnother:
    async def test_steps_files_lines_and_commits(self, db_session, project, repo) -> None:
        path, shas = repo
        start = datetime(2026, 11, 1, tzinfo=UTC)
        first = await _reading(db_session, project, shas[0], {"app/a.py": "x = 1\n"}, start)
        second = await _reading(db_session, project, shas[2], {"app/a.py": "x = 2\n", "app/b.py": "y = 1\n"}, start + timedelta(days=1))
        await CommitRepository(db_session).store(project.id, read_commits(path))
        await db_session.commit()

        steps = await HistoryService(db_session, project.id).steps()
        assert [s.reading.id for s in steps] == [second.id, first.id]
        top = steps[0]
        assert top.previous == first.id and top.files == 2
        assert top.changed == {"modified": 1, "added": 1} and (top.added, top.removed) == (2, 1)
        assert (top.commits, top.commits_complete) == (2, True)
        assert steps[1].previous is None

        found = await HistoryService(db_session, project.id).between(first, second)
        assert [c.subject for c in found.commits] == ["Change a, add b", "Docs only, outside app/"]

    async def test_a_reading_without_files_says_so(self, db_session, project) -> None:
        start = datetime(2026, 11, 1, tzinfo=UTC)
        old = await _reading(db_session, project, "a" * 40, None, start)
        await _reading(db_session, project, "b" * 40, {"x.py": "1\n"}, start + timedelta(days=1))
        await db_session.commit()
        steps = await HistoryService(db_session, project.id).steps()
        assert steps[0].missing == [old.id] and steps[0].changed == {}

    async def test_one_files_history(self, db_session, project) -> None:
        start = datetime(2026, 11, 1, tzinfo=UTC)
        one = await _reading(db_session, project, "1" * 40, {"a.py": "1\n"}, start)
        await _reading(db_session, project, "2" * 40, {"a.py": "1\n", "b.py": "x\n"}, start + timedelta(days=1))
        three = await _reading(db_session, project, "3" * 40, {"a.py": "2\n"}, start + timedelta(days=2))
        four = await _reading(db_session, project, "4" * 40, {"b.py": "x\n"}, start + timedelta(days=3))
        await db_session.commit()
        steps = await HistoryService(db_session, project.id).file("a.py")
        assert [(s.reading.id, s.status) for s in steps] == [(four.id, "removed"), (three.id, "modified"), (one.id, "added")]


class TestKeeping:
    async def test_prune_keeps_the_newest_and_sweep_frees_the_rest(self, db_session, project) -> None:
        start = datetime(2026, 11, 1, tzinfo=UTC)
        unique = f"only in the oldest {uuid.uuid4().hex}\n"
        old = await _reading(db_session, project, "1" * 40, {"a.py": unique}, start)
        await _reading(db_session, project, "2" * 40, {"a.py": "shared\n"}, start + timedelta(days=1))
        new = await _reading(db_session, project, "3" * 40, {"a.py": "shared\n"}, start + timedelta(days=2))
        repo = SourceRepository(db_session)
        assert await repo.prune(project.id, 2) == 1
        assert not await repo.has_snapshot(old.id) and await repo.has_snapshot(new.id)
        await repo.sweep()
        from codelith.db.repositories.knowledge.source_repo import blob_hash

        assert await db_session.get(SourceBlob, blob_hash(unique)) is None
        assert await repo.prune(project.id, 0) == 0

    async def test_fetching_history_from_a_local_folder(self, db_session, project, repo) -> None:
        path, shas = repo
        db_session.add(ProjectSource(project_id=project.id, source_type="local", url_or_path=str(path)))
        await _reading(db_session, project, shas[2], None, datetime(2026, 11, 1, tzinfo=UTC))
        await db_session.commit()
        done = await HistoryService(db_session, project.id).fetch()
        assert (done.ok, done.commits, done.new) == (True, 3, 3)
        again = await HistoryService(db_session, project.id).fetch()
        assert again.new == 0
        n = (await db_session.execute(select(func.count()).where(SourceCommit.project_id == project.id))).scalar_one()
        assert n == 3

    async def test_an_upload_has_no_history(self, db_session, project) -> None:
        done = await HistoryService(db_session, project.id).fetch()
        assert not done.ok and "no git source" in done.reason


class TestOverHttp:
    async def test_history_commits_file_history_storage_and_a_file_as_it_was(self, db_session, project, repo, client) -> None:
        from codelith.core.security import create_access_token
        from codelith.models.user import User

        path, shas = repo
        start = datetime(2026, 11, 1, tzinfo=UTC)
        first = await _reading(db_session, project, shas[0], {"app/a.py": "x = 1\n"}, start)
        second = await _reading(db_session, project, shas[2], {"app/a.py": "x = 2\n"}, start + timedelta(days=1))
        await CommitRepository(db_session).store(project.id, read_commits(path))
        user = User(org_id=project.org_id, email=f"hi-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
                    full_name="HI", role="manager", is_active=True)
        db_session.add(user)
        await db_session.commit()
        h = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
        base = f"/api/v1/projects/{project.id}"

        steps = (await client.get(f"{base}/history", headers=h)).json()
        assert [s["reading"]["id"] for s in steps] == [second.id, first.id] and steps[0]["commits"] == 2

        commits = (await client.get(f"{base}/compare/commits", params={"before": first.id, "after": second.id}, headers=h)).json()
        assert commits["known"] and commits["complete"]
        assert [c["subject"] for c in commits["commits"]] == ["Change a, add b", "Docs only, outside app/"]
        assert "author" in commits["commits"][0] and "email" not in commits["commits"][0]

        files = (await client.get(f"{base}/file-history", params={"path": "app/a.py"}, headers=h)).json()
        assert [(f["reading"]["id"], f["status"]) for f in files] == [(second.id, "modified"), (first.id, "added")]

        old = (await client.get(f"{base}/files/app/a.py", params={"reading": first.id}, headers=h)).json()
        assert "x = 1" in "".join(s.get("text", "") for s in old["segments"])

        storage = (await client.get("/api/v1/settings/storage", headers=h)).json()
        mine = next(c for c in storage["codebases"] if c["id"] == project.id)
        assert mine["readings_with_files"] == 2 and storage["keep_readings"] == 0
