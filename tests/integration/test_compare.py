"""
Two readings compared line by line, from the files each one kept: what was added,
removed, changed or renamed, by how many lines, and each changed line with the words
that changed in it marked.
"""

from __future__ import annotations

import uuid

import pytest_asyncio

from codelith.db.repositories.knowledge.source_repo import SnapshotFile, SourceRepository
from codelith.knowledge.compare import CompareService, diff_rows
from codelith.knowledge.constants import KBStatus
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project

LONG = "".join(f"def step_{i}(x):\n    return x + {i}\n\n" for i in range(30))

BEFORE = {
    "app/main.py": "import os\n\nPORT = 8000\n\n\ndef run():\n    return PORT\n",
    "app/old_name.py": LONG,
    "app/legacy.py": "print('bye')\n",
    "app/same.py": "x = 1\n",
    "app/moved.py": "y = 2\n",
}
AFTER = {
    "app/main.py": "import os\n\nPORT = 9000\n\n\ndef run():\n    return PORT\n",
    "app/new_name.py": LONG.replace("x + 0", "x + 100"),
    "app/same.py": "x = 1\n",
    "lib/moved.py": "y = 2\n",
    "app/fresh.py": "def hello():\n    return 'hi'\n",
}


@pytest_asyncio.fixture
async def readings(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-cmp-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="cmp", slug=f"cmp-{tag}")
    db_session.add(project)
    await db_session.flush()
    sources = SourceRepository(db_session)
    out = []
    for files in (BEFORE, AFTER):
        kb = KnowledgeBase(project_id=project.id, commit_sha=uuid.uuid4().hex, status=KBStatus.READY)
        db_session.add(kb)
        await db_session.flush()
        await sources.store(kb.id, [SnapshotFile(path=p, content=c, language="python") for p, c in files.items()])
        out.append(kb)
    return out


class TestWhatChanged:
    async def test_each_file_has_its_status(self, db_session, readings) -> None:
        result = await CompareService(db_session).files(*readings)
        assert result.available
        status = {f.path: (f.status, f.old_path) for f in result.files}
        assert status == {
            "app/main.py": ("modified", None),
            "app/new_name.py": ("renamed", "app/old_name.py"),
            "lib/moved.py": ("renamed", "app/moved.py"),
            "app/fresh.py": ("added", None),
            "app/legacy.py": ("removed", None),
        }

    async def test_lines_are_counted(self, db_session, readings) -> None:
        files = {f.path: f for f in (await CompareService(db_session).files(*readings)).files}
        assert (files["app/main.py"].added, files["app/main.py"].removed) == (1, 1)
        assert (files["app/fresh.py"].added, files["app/legacy.py"].removed) == (2, 1)
        # Moved untouched: identical content, nothing to count.
        assert files["lib/moved.py"].similarity == 1.0 and files["lib/moved.py"].added == 0
        renamed = files["app/new_name.py"]
        assert 0.6 <= renamed.similarity < 1.0 and (renamed.added, renamed.removed) == (1, 1)

    async def test_a_reading_without_files_says_which(self, db_session, readings) -> None:
        old = KnowledgeBase(project_id=readings[0].project_id, commit_sha="o" * 40, status=KBStatus.READY)
        db_session.add(old)
        await db_session.flush()
        result = await CompareService(db_session).files(old, readings[1])
        assert not result.available and result.missing == [old.id]


class TestOneFile:
    async def test_every_line_with_the_changed_words_marked(self, db_session, readings) -> None:
        diff = await CompareService(db_session).file(*readings, "app/main.py")
        assert diff.status == "modified" and diff.whole and (diff.old_lines, diff.new_lines) == (7, 7)
        changed = [r for r in diff.rows if r.kind != "context"]
        assert [(r.kind, r.old, r.new, r.text) for r in changed] == [
            ("del", 3, None, "PORT = 8000"),
            ("add", None, 3, "PORT = 9000"),
        ]
        assert changed[0].marks == [(7, 11)] and changed[1].marks == [(7, 11)]
        assert len(diff.rows) == 8

    async def test_a_renamed_file_is_diffed_against_its_old_path(self, db_session, readings) -> None:
        diff = await CompareService(db_session).file(*readings, "app/new_name.py", "app/old_name.py")
        assert diff.status == "renamed" and diff.old_path == "app/old_name.py"
        assert [r.text for r in diff.rows if r.kind == "add"] == ["    return x + 100"]

    async def test_an_added_file_is_all_additions(self, db_session, readings) -> None:
        diff = await CompareService(db_session).file(*readings, "app/fresh.py")
        assert diff.status == "added" and all(r.kind == "add" for r in diff.rows)


def test_hunks_keep_three_lines_around_each_change() -> None:
    a = [f"line {i}" for i in range(40)]
    b = list(a)
    b[20] = "changed"
    rows = diff_rows(a, b, context=3)
    assert [r.old for r in rows if r.kind == "context"] == [18, 19, 20, 22, 23, 24]


def test_a_line_rewritten_end_to_end_marks_nothing() -> None:
    rows = diff_rows(["alpha beta gamma"], ["completely different words here"])
    assert all(not r.marks for r in rows)
