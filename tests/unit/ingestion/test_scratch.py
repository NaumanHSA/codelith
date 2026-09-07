"""
Clones are removed; the user's own folder is not.

This module deletes directories, so the tests that matter most are the ones that prove
it refuses to. A `local` source hands its own path straight through as `local_path`,
and the one bug worth being paranoid about here is the one that reaches it.
"""

import os
import stat
import uuid

import pytest

from codelith.ingestion import scratch


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A scratch root of our own, so nothing here can touch a real one."""
    r = tmp_path / "repos"
    r.mkdir()

    settings = type("S", (), {"REPO_SCRATCH_DIR": str(r)})()
    monkeypatch.setattr(scratch, "get_settings", lambda: settings)
    # Each test starts with nothing registered: the context variable outlives a test.
    scratch._created.set(None)
    return r


def _clone(root, files=("a.py",)):
    """A directory shaped like one the git ingesters make."""
    d = root / str(uuid.uuid4())
    d.mkdir()
    for name in files:
        (d / name).write_text("x = 1", encoding="utf-8")
    return d


class TestItRemovesWhatItMade:
    def test_a_tracked_clone_is_discarded(self, root):
        d = _clone(root)
        scratch.track(d)

        assert scratch.discard() == 1
        assert not d.exists()

    def test_several_clones_in_one_run(self, root):
        clones = [_clone(root) for _ in range(3)]
        for d in clones:
            scratch.track(d)

        assert scratch.discard() == 3
        assert not any(d.exists() for d in clones)

    def test_discard_empties_the_register(self, root):
        """A second call must not re-report work the first one did."""
        scratch.track(_clone(root))

        assert scratch.discard() == 1
        assert scratch.discard() == 0

    def test_a_clone_already_gone_is_not_counted(self, root):
        import shutil

        d = _clone(root)
        scratch.track(d)
        shutil.rmtree(d)

        assert scratch.discard() == 0


class TestItRefusesWhatItDidNotMake:
    def test_a_path_outside_the_root_is_refused(self, root, tmp_path):
        """The failure this exists to prevent: a `local` source is the user's code."""
        theirs = tmp_path / "my-project"
        theirs.mkdir()
        (theirs / "main.py").write_text("print('mine')", encoding="utf-8")

        scratch.track(theirs)

        assert scratch.discard() == 0
        assert theirs.exists()
        assert (theirs / "main.py").exists()

    def test_a_nested_path_inside_the_root_is_refused(self, root):
        """Only direct children. A subdirectory of a clone is not a clone."""
        d = _clone(root)
        inner = d / "src"
        inner.mkdir()

        scratch.track(inner)

        assert scratch.discard() == 0
        assert inner.exists()

    def test_a_non_uuid_child_is_refused(self, root):
        """`uploads/` holds the only copy of an uploaded archive."""
        uploads = root / "uploads"
        uploads.mkdir()
        (uploads / "7").mkdir()

        scratch.track(uploads)

        assert scratch.discard() == 0
        assert uploads.exists()


class TestTheSweep:
    def test_it_removes_clones_from_earlier_runs(self, root):
        """Nothing is tracked — these are the ones a previous process left."""
        old = [_clone(root) for _ in range(4)]

        assert scratch.sweep() == 4
        assert not any(d.exists() for d in old)

    def test_it_leaves_uploads_alone(self, root):
        uploads = root / "uploads" / "3"
        uploads.mkdir(parents=True)
        (uploads / "archive.zip").write_text("zip", encoding="utf-8")
        stale = _clone(root)

        assert scratch.sweep() == 1
        assert not stale.exists()
        assert (uploads / "archive.zip").exists()

    def test_it_leaves_loose_files_alone(self, root):
        note = root / "README"
        note.write_text("not a clone", encoding="utf-8")

        assert scratch.sweep() == 0
        assert note.exists()

    def test_a_missing_root_is_not_an_error(self, root):
        import shutil

        shutil.rmtree(root)
        assert scratch.sweep() == 0


class TestTheLocalIngesterRegistersNothing:
    """
    The guarantee is structural, not conditional: `LocalRepoIngester` returns the
    user's own path as `local_path` and never calls `track`, so no later change to
    `discard` can reach it. Asserted through the ingester rather than by reading the
    source, because that is the property that has to hold.
    """

    @pytest.mark.asyncio
    async def test_reading_a_folder_leaves_nothing_to_discard(self, root, tmp_path):
        from codelith.ingestion.repo.local import LocalRepoIngester

        theirs = tmp_path / "their-repo"
        theirs.mkdir()
        (theirs / "app.py").write_text("print('hi')", encoding="utf-8")

        result = await LocalRepoIngester().clone(str(theirs))

        assert result.local_path == theirs.resolve()
        assert scratch.discard() == 0
        assert (theirs / "app.py").exists()


class TestReadOnlyFiles:
    """
    Every clone has a `.git`, and git marks its pack files read-only. On Windows a
    read-only file cannot be unlinked, so `rmtree` raised on the first one and the
    cleanup removed nothing at all — 32 directories, 1.7 GB, every one refused. The
    retry handler is the whole reason this works on the platform most of its users
    are on.
    """

    def test_a_read_only_file_does_not_stop_the_delete(self, root):
        d = _clone(root)
        packed = d / ".git" / "objects" / "pack"
        packed.mkdir(parents=True)
        idx = packed / "pack-abc.idx"
        idx.write_text("binary-ish", encoding="utf-8")
        os.chmod(idx, stat.S_IREAD)

        scratch.track(d)

        assert scratch.discard() == 1
        assert not d.exists()

    def test_the_sweep_handles_them_too(self, root):
        d = _clone(root)
        ro = d / "locked.pack"
        ro.write_text("x", encoding="utf-8")
        os.chmod(ro, stat.S_IREAD)

        assert scratch.sweep() == 1
        assert not d.exists()
