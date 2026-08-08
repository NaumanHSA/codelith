"""
Markdown paths, which have to live in the same address space as code.

Found by indexing prose for real and reading the rows back: markdown chunks stored
`repos\\54816587-1b3d-…\\docs\\index.md` while the code chunks beside them stored
`neurosurfer/config.py`. Two consequences, both quiet:

* Nothing can join a prose chunk to the code it describes — which is the entire
  reason prose is indexed, since its value is being a router.
* The clone sandbox's directory name is persisted into the knowledge base, and it
  differs on every ingestion of the same repository.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.parsers.markdown_parser import MarkdownParser


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("# Project\n\nText.\n", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\nMore.\n", encoding="utf-8")
    return tmp_path


class TestPathsAreRepositoryRelative:
    def test_paths_are_relative_to_the_repository_root(self, tmp_path: Path) -> None:
        docs = MarkdownParser().parse_directory(_repo(tmp_path))

        assert {d.path for d in docs} == {"README.md", "docs/guide.md"}

    def test_no_absolute_or_native_separators_survive(self, tmp_path: Path) -> None:
        """A stored path containing the sandbox directory is both unjoinable and
        different on every run."""
        docs = MarkdownParser().parse_directory(_repo(tmp_path))

        for doc in docs:
            assert "\\" not in doc.path
            assert not Path(doc.path).is_absolute()
            assert tmp_path.name not in doc.path

    def test_a_single_file_parse_can_still_be_relative(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)

        doc = MarkdownParser().parse_file(root / "docs" / "guide.md", root)

        assert doc.path == "docs/guide.md"


class TestVendoredDocsAreSkipped:
    def test_dependency_documentation_is_not_indexed(self, tmp_path: Path) -> None:
        """`node_modules` and `.venv` are full of markdown documenting somebody
        else's software. Indexed, it answers questions about a dependency as though
        it were about this project."""
        root = _repo(tmp_path)
        for vendor in ("node_modules", ".venv"):
            (root / vendor).mkdir()
            (root / vendor / "READ.md").write_text("# Other\n", encoding="utf-8")

        docs = MarkdownParser().parse_directory(root)

        assert {d.path for d in docs} == {"README.md", "docs/guide.md"}

    def test_the_projects_own_docs_are_kept(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        (root / "docs" / "adr").mkdir()
        (root / "docs" / "adr" / "0001.md").write_text("# Decision\n", encoding="utf-8")

        docs = MarkdownParser().parse_directory(root)

        assert "docs/adr/0001.md" in {d.path for d in docs}


class TestContentIsUnchanged:
    def test_headings_and_content_still_parse(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)

        doc = next(d for d in MarkdownParser().parse_directory(root) if d.path == "README.md")

        assert doc.headings == ["Project"]
        assert "Text." in doc.content
        assert doc.size_bytes > 0
