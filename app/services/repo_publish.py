"""
Writing generated documentation back into the repository it describes.

Exports land in a downloaded archive today, which makes this a place you visit. A
branch in the repository makes it part of the workflow: the docs sit beside the code,
review happens where review already happens, and the diff is the unit of attention.

Two things this module is careful about, because both are ways to damage somebody's
repository:

* **It only writes files it would have written.** Every path is derived from a
  section and page slug and forced to stay inside the target directory. A slug
  containing `../` is refused rather than sanitised into something plausible.
* **It never deletes what it did not create.** A page retired from the site leaves a
  file behind, and that file is *reported* rather than removed. The alternative —
  deleting anything in `docs/` that no longer matches a page — would eventually eat
  a hand-written file that happened to live there.

The plan is computed separately from being applied, so what would change can be shown
before anything is written. That separation is also what makes this testable without
a repository.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import structlog

from app.formatters.site_tree import SiteTree

logger = structlog.get_logger(__name__)

#: Where documentation goes unless a project says otherwise.
DEFAULT_DOCS_DIR = "docs"

#: Written at the root of the target directory so a reader knows what produced the
#: files and can find the commit they describe.
_README_NAME = "README.md"


@dataclass(frozen=True, slots=True)
class FileChange:
    """One file the publish would write."""

    path: str
    content: str
    #: "add" | "update" | "unchanged"
    action: str

    @property
    def writes(self) -> bool:
        return self.action != "unchanged"


@dataclass(slots=True)
class PublishPlan:
    """
    Everything a publish would do, before it does any of it.

    Held as data so the studio can show a diff summary, and so the risky half — git
    — can be tested separately from the half that decides what should change.
    """

    docs_dir: str
    changes: list[FileChange] = field(default_factory=list)
    #: Files under `docs_dir` that no page maps onto. Reported, never deleted.
    orphans: list[str] = field(default_factory=list)
    #: Slugs refused for trying to escape `docs_dir`.
    rejected: list[str] = field(default_factory=list)

    @property
    def writes(self) -> list[FileChange]:
        return [c for c in self.changes if c.writes]

    @property
    def is_empty(self) -> bool:
        return not self.writes

    def summary(self) -> dict:
        return {
            "docs_dir": self.docs_dir,
            "added": sum(1 for c in self.changes if c.action == "add"),
            "updated": sum(1 for c in self.changes if c.action == "update"),
            "unchanged": sum(1 for c in self.changes if c.action == "unchanged"),
            "orphans": len(self.orphans),
            "rejected": len(self.rejected),
        }


def build_plan(
    tree: SiteTree,
    repo_root: Path | str,
    docs_dir: str = DEFAULT_DOCS_DIR,
    *,
    include_index: bool = True,
) -> PublishPlan:
    """
    What publishing this site into `repo_root/docs_dir` would change.

    Compares against what is on disk, so a page whose prose has not moved produces
    no diff. That is what makes this runnable on every generation rather than only
    when someone remembers — a no-op publish should be a no-op commit.
    """
    root = Path(repo_root)
    target = (root / docs_dir).resolve()
    plan = PublishPlan(docs_dir=docs_dir)

    written: set[str] = set()

    if include_index:
        index = _index_markdown(tree)
        _record(plan, root, target, f"{docs_dir}/{_README_NAME}", index, written)

    for section in tree.sections:
        for page in section.pages:
            relative = _page_path(docs_dir, section.slug, page.slug)
            if relative is None:
                plan.rejected.append(f"{section.slug}/{page.slug}")
                continue
            _record(plan, root, target, relative, _page_markdown(page), written)

    plan.orphans = _orphans(target, root, written)
    return plan


def _record(
    plan: PublishPlan,
    root: Path,
    target: Path,
    relative: str,
    content: str,
    written: set[str],
) -> None:
    absolute = (root / relative).resolve()
    # Belt and braces: `_page_path` already refuses traversal, but a slug is
    # attacker-adjacent input and this is the last point before a filesystem write.
    if not _inside(absolute, target):
        plan.rejected.append(relative)
        return

    written.add(relative)
    existing = _read(absolute)
    if existing is None:
        plan.changes.append(FileChange(path=relative, content=content, action="add"))
    elif _digest(existing) == _digest(content):
        plan.changes.append(FileChange(path=relative, content=content, action="unchanged"))
    else:
        plan.changes.append(FileChange(path=relative, content=content, action="update"))


def _page_path(docs_dir: str, section_slug: str, slug: str) -> str | None:
    """
    `docs/section/page.md`, or `None` if the slugs try to escape.

    Refused rather than sanitised. A slug containing `..` is either a bug or an
    attack, and quietly rewriting it into a valid path writes a file somebody did
    not ask for under a name they will not recognise.
    """
    for part in (section_slug, slug):
        if not part or part in (".", ".."):
            return None
        if "/" in part or "\\" in part or ".." in part:
            return None
    return f"{docs_dir}/{section_slug}/{slug}.md"


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _digest(text: str) -> str:
    """
    Content identity, insensitive to line endings and trailing whitespace.

    Without the normalisation every file looks changed the first time this runs on
    Windows, and a publish that rewrites forty untouched files is indistinguishable
    from one that fixed something.
    """
    normalised = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    return hashlib.blake2b(normalised.strip().encode("utf-8"), digest_size=16).hexdigest()


def _orphans(target: Path, root: Path, written: set[str]) -> list[str]:
    """Markdown under the docs directory that no page maps onto."""
    if not target.is_dir():
        return []
    out: list[str] = []
    for path in sorted(target.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if relative not in written:
            out.append(relative)
    return out


def _page_markdown(page) -> str:
    """
    One page, with provenance in the front matter.

    The provenance is the point of publishing into the repository rather than
    alongside it: a reader looking at a file in `docs/` can see which commit it
    describes and which sources it was written from, without leaving the diff.
    """
    lines = ["---", f'title: "{page.title}"']
    if getattr(page, "intent", None):
        lines.append(f'intent: "{_escape(page.intent)}"')
    if getattr(page, "commit_sha", None):
        lines.append(f"generated_from_commit: {page.commit_sha}")
    if sources := list(getattr(page, "source_files", []) or []):
        lines.append("sources:")
        lines.extend(f"  - {s}" for s in sources[:20])
    lines.append("generated_by: document-anything")
    lines.append("---")
    lines.append("")
    lines.append(page.content_markdown.strip())
    lines.append("")
    return "\n".join(lines)


def _index_markdown(tree: SiteTree) -> str:
    """A table of contents, so the directory is navigable on the forge."""
    lines = [f"# {tree.title}", ""]
    if tree.home_markdown:
        lines += [tree.home_markdown.strip(), ""]
    lines += [
        "> Generated by document-anything. Edits here are overwritten by the next "
        "publish — change the source, or revise the page in the studio.",
        "",
    ]
    for section in tree.sections:
        if not section.pages:
            continue
        lines.append(f"## {section.title}")
        lines.append("")
        for page in section.pages:
            lines.append(f"- [{page.title}]({section.slug}/{page.slug}.md)")
        lines.append("")
    return "\n".join(lines)


def _escape(text: str) -> str:
    return str(text).replace('"', "'").replace("\n", " ")


__all__ = ["build_plan", "PublishPlan", "FileChange", "DEFAULT_DOCS_DIR"]
