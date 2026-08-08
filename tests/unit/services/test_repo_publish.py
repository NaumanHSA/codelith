"""
Publishing documentation back into the repository it describes.

Exports land in a downloaded archive, which makes the tool a place you visit. A
branch makes it part of the workflow. But writing into somebody's repository is the
most destructive thing in this codebase, so most of these cases are about restraint:

* **Only files it would have written.** Every path comes from a section and page
  slug and is forced to stay inside the docs directory. A slug containing `..` is
  refused, not sanitised — quietly rewriting it writes a file nobody asked for under
  a name nobody will recognise.
* **Never deletes what it did not create.** A retired page leaves its file behind and
  is reported. Deleting anything in `docs/` that no longer matches a page would
  eventually eat a hand-written file that happened to live there.
* **A no-op publish is a no-op.** Publishing twice without regenerating must leave no
  branch, no commit and no rewritten files, or nobody will run it on every change.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.formatters.site_tree import ExportPage, ExportSection, SiteTree
from app.services.repo_publish import build_plan
from app.services.repo_publish_git import GitError, apply_plan


def _tree(**overrides) -> SiteTree:
    return SiteTree(
        title="Neurosurfer Docs",
        sections=[
            ExportSection(
                slug="architecture",
                title="Architecture",
                pages=[
                    ExportPage(
                        section_slug="architecture",
                        slug="overview",
                        title="Overview",
                        content_markdown="# Overview\n\nHow the system fits together.\n",
                        intent="orient a new reader",
                        commit_sha="4065c2fc",
                        source_files=["app/main.py"],
                    ),
                ],
            ),
        ],
        home_markdown="The documentation site.",
        **overrides,
    )


class TestPlanning:
    def test_a_page_becomes_a_file_under_the_docs_directory(self, tmp_path: Path) -> None:
        plan = build_plan(_tree(), tmp_path)

        paths = {c.path for c in plan.changes}
        assert "docs/architecture/overview.md" in paths
        assert "docs/README.md" in paths

    def test_everything_is_an_add_on_an_empty_repository(self, tmp_path: Path) -> None:
        plan = build_plan(_tree(), tmp_path)

        assert all(c.action == "add" for c in plan.changes)
        assert plan.summary()["added"] == 2

    def test_provenance_travels_with_the_page(self, tmp_path: Path) -> None:
        """The reason to publish into the repository rather than beside it: a reader
        in the diff can see which commit the page describes."""
        plan = build_plan(_tree(), tmp_path)

        page = next(c for c in plan.changes if c.path.endswith("overview.md"))
        assert "generated_from_commit: 4065c2fc" in page.content
        assert "app/main.py" in page.content

    def test_the_index_links_every_page(self, tmp_path: Path) -> None:
        plan = build_plan(_tree(), tmp_path)

        index = next(c for c in plan.changes if c.path.endswith("README.md"))
        assert "architecture/overview.md" in index.content

    def test_a_custom_docs_directory_is_honoured(self, tmp_path: Path) -> None:
        plan = build_plan(_tree(), tmp_path, docs_dir="documentation")

        assert all(c.path.startswith("documentation/") for c in plan.changes)


class TestNothingChangesTwice:
    """A publish that rewrites untouched files is indistinguishable from one that
    fixed something, so nobody would run it on every generation."""

    def test_republishing_identical_content_writes_nothing(self, tmp_path: Path) -> None:
        first = build_plan(_tree(), tmp_path)
        for change in first.writes:
            path = tmp_path / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.content, encoding="utf-8")

        second = build_plan(_tree(), tmp_path)

        assert second.is_empty
        assert all(c.action == "unchanged" for c in second.changes)

    def test_line_endings_do_not_count_as_a_change(self, tmp_path: Path) -> None:
        """
        A repository checked out on Windows has CRLF on disk. Without the
        normalisation the first publish rewrites every file, and a publish that
        rewrites forty untouched files is indistinguishable from one that fixed
        something.

        Written as bytes deliberately: `write_text` translates newlines a second
        time and produces `\\r\\r\\n`, which reads back as a genuinely different
        document rather than the same one with different line endings.
        """
        plan = build_plan(_tree(), tmp_path)
        for change in plan.writes:
            path = tmp_path / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(change.content.replace("\n", "\r\n").encode("utf-8"))

        assert build_plan(_tree(), tmp_path).is_empty

    def test_edited_prose_is_an_update(self, tmp_path: Path) -> None:
        plan = build_plan(_tree(), tmp_path)
        for change in plan.writes:
            path = tmp_path / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.content + "\nsomething else\n", encoding="utf-8")

        second = build_plan(_tree(), tmp_path)

        assert second.summary()["updated"] == 2


class TestItNeverEscapesTheDocsDirectory:
    def test_a_traversing_section_slug_is_refused(self, tmp_path: Path) -> None:
        """The section slug is the path segment `build_plan` actually uses — an
        earlier version of this test set `page.section_slug`, which the planner
        never reads, and so proved nothing."""
        tree = _tree()
        tree.sections[0].slug = "../../etc"

        plan = build_plan(tree, tmp_path)

        assert plan.rejected == ["../../etc/overview"]
        assert not any("etc" in c.path for c in plan.changes)
        assert not (tmp_path.parent.parent / "etc").exists()

    def test_a_slash_in_a_page_slug_is_refused(self, tmp_path: Path) -> None:
        tree = _tree()
        tree.sections[0].pages[0] = ExportPage(
            section_slug="architecture", slug="a/b", title="Bad", content_markdown="x"
        )

        plan = build_plan(tree, tmp_path)

        assert "architecture/a/b" in plan.rejected

    def test_an_empty_page_slug_is_refused(self, tmp_path: Path) -> None:
        tree = _tree()
        tree.sections[0].pages[0] = ExportPage(
            section_slug="architecture", slug="", title="Bad", content_markdown="x"
        )

        plan = build_plan(tree, tmp_path)

        assert plan.rejected


class TestItNeverDeletes:
    def test_a_file_no_page_maps_onto_is_reported_not_removed(self, tmp_path: Path) -> None:
        """Deleting anything unmatched would eventually eat a hand-written file that
        happened to live in the docs directory."""
        handwritten = tmp_path / "docs" / "CONTRIBUTING.md"
        handwritten.parent.mkdir(parents=True)
        handwritten.write_text("# By hand\n", encoding="utf-8")

        plan = build_plan(_tree(), tmp_path)

        assert "docs/CONTRIBUTING.md" in plan.orphans
        assert handwritten.exists()

    def test_a_retired_page_leaves_its_file(self, tmp_path: Path) -> None:
        first = build_plan(_tree(), tmp_path)
        for change in first.writes:
            path = tmp_path / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.content, encoding="utf-8")

        empty = SiteTree(title="Neurosurfer Docs", sections=[], home_markdown=None)
        plan = build_plan(empty, tmp_path)

        assert "docs/architecture/overview.md" in plan.orphans


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    return tmp_path


class TestApplying:
    def test_files_are_committed_on_a_new_branch(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        plan = build_plan(_tree(), repo)

        result = apply_plan(plan, repo, branch="docs/update", message="docs: update")

        assert result.commit
        assert result.files_written == 2
        assert (repo / "docs" / "architecture" / "overview.md").exists()

    def test_an_empty_plan_creates_no_branch_and_no_commit(self, tmp_path: Path) -> None:
        """Publishing twice without regenerating should leave no trace, not an empty
        commit and a dangling branch."""
        repo = _init_repo(tmp_path)
        apply_plan(build_plan(_tree(), repo), repo, branch="docs/one", message="docs")

        second = apply_plan(build_plan(_tree(), repo), repo, branch="docs/two", message="docs")

        assert second.nothing_to_do
        assert second.commit is None
        branches = subprocess.run(
            ["git", "branch", "--list", "docs/two"], cwd=repo, capture_output=True, text=True
        ).stdout
        assert branches.strip() == ""

    def test_only_the_docs_directory_is_committed(self, tmp_path: Path) -> None:
        """A publish must not sweep up whatever the user had in progress."""
        repo = _init_repo(tmp_path)
        (repo / "unrelated.py").write_text("x = 1\n", encoding="utf-8")

        apply_plan(build_plan(_tree(), repo), repo, branch="docs/update", message="docs")

        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
        ).stdout
        assert "unrelated.py" in status  # still uncommitted, as the user left it

    def test_a_non_repository_is_refused(self, tmp_path: Path) -> None:
        plan = build_plan(_tree(), tmp_path)

        with pytest.raises(GitError):
            apply_plan(plan, tmp_path, branch="docs/update", message="docs")

    def test_nothing_is_pushed(self, tmp_path: Path) -> None:
        """The product's claim is that nothing leaves the machine. Pushing is a
        separate, explicitly-authorised step — `apply_plan` has no remote access at
        all, which is asserted here so a later refactor cannot quietly add one."""
        import inspect

        from app.services import repo_publish_git

        source = inspect.getsource(repo_publish_git)
        for forbidden in ('"push"', "'push'", "remote", "gh ", "api.github.com"):
            assert forbidden not in source, f"{forbidden} reached the local publish path"
