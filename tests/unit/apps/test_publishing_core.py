"""
The two things publishing has to get right before it builds anything.

**The fingerprint**, because it decides whether a publish happens at all. If it
misses a change the studio serves a stale site and reports it as current, which is
worse than not publishing.

**Path resolution**, because it is the only thing standing between a published site
and the rest of the disk. The invariant is not "these particular strings are
rejected" — a list of known-bad strings is a list somebody will find a gap in. It is
that *nothing* resolves outside the build directory, whatever it is spelled like.
"""

from __future__ import annotations

import pytest

from codelith.apps.documentation.formatters.site_tree import (
    ExportPage,
    ExportSection,
    SiteTree,
)
from codelith.apps.documentation.publishing import paths
from codelith.apps.documentation.publishing.fingerprint import content_hash


def _tree(*, title="Demo", order=(0, 1), body_a="# A", section_title="Guides"):
    pages = [
        ExportPage(
            section_slug="guides", slug="a", title="A", content_markdown=body_a,
            order_index=order[0], intent=None, commit_sha=None, source_files=[],
        ),
        ExportPage(
            section_slug="guides", slug="b", title="B", content_markdown="# B",
            order_index=order[1], intent=None, commit_sha=None, source_files=[],
        ),
    ]
    return SiteTree(
        title=title,
        sections=[ExportSection(slug="guides", title=section_title, pages=pages)],
        home_markdown="# Home",
        version_label=None,
    )


def _hash(tree, renderer="builtin", version="1"):
    return content_hash(tree, renderer=renderer, renderer_version=version)


class TestFingerprint:
    def test_same_tree_hashes_the_same(self):
        """Otherwise every publish rebuilds, and the unchanged case never fires."""
        assert _hash(_tree()) == _hash(_tree())

    def test_it_is_a_sha256(self):
        assert len(_hash(_tree())) == 64

    @pytest.mark.parametrize(
        "changed,why",
        [
            (dict(title="Other"), "the site title is on every page"),
            (dict(order=(1, 0)), "nav order is a real change to the site"),
            (dict(body_a="# A changed"), "the prose is the point"),
            (dict(section_title="Handbook"), "section titles are rendered"),
        ],
    )
    def test_anything_that_changes_the_output_changes_the_hash(self, changed, why):
        assert _hash(_tree()) != _hash(_tree(**changed)), why

    def test_a_different_renderer_is_a_different_site(self):
        assert _hash(_tree()) != _hash(_tree(), renderer="mkdocs")

    def test_a_new_renderer_version_forces_a_rebuild(self):
        """
        Without this an upgraded renderer reports the site as unchanged, and the
        published HTML stays older than the code that renders it.
        """
        assert _hash(_tree()) != _hash(_tree(), version="2")

    def test_page_fields_cannot_be_smuggled_across_a_boundary(self):
        """
        Length-prefixed rather than separator-joined. Moving text from one field to
        the next must not produce the same digest.
        """
        one = _tree()
        two = _tree()
        one.sections[0].pages[0].title = "AB"
        one.sections[0].pages[0].slug = ""
        two.sections[0].pages[0].title = "A"
        two.sections[0].pages[0].slug = "B"
        assert _hash(one) != _hash(two)


class TestPathResolution:
    """The serving route's whole defence."""

    @pytest.fixture
    def root(self, tmp_path):
        d = tmp_path / "build"
        (d / "assets").mkdir(parents=True)
        (d / "index.html").write_text("<h1>hi</h1>")
        (d / "assets" / "theme.css").write_text("body{}")
        (tmp_path / "secret.txt").write_text("not yours")
        return d

    @pytest.mark.parametrize(
        "requested",
        [
            "index.html",
            "/index.html",           # a web path, and the common case
            "assets/theme.css",
            "",                      # the directory itself
        ],
    )
    def test_files_inside_resolve(self, root, requested):
        assert paths.resolve_within(root, requested) is not None

    @pytest.mark.parametrize(
        "requested",
        [
            "../secret.txt",
            "../../secret.txt",
            "assets/../../secret.txt",
            "..",
            "a/b/../../../secret.txt",
            "\\..\\secret.txt",
            "./../secret.txt",
        ],
    )
    def test_escapes_are_refused(self, root, requested):
        assert paths.resolve_within(root, requested) is None

    @pytest.mark.parametrize(
        "requested",
        [
            "index.html", "/index.html", "../secret.txt", "..", "a/../../b",
            "%2e%2e/x", "/etc/passwd", "....//secret.txt", "assets/./theme.css",
            "\\\\server\\share", "C:/Windows/system.ini",
        ],
    )
    def test_nothing_ever_resolves_outside_the_build(self, root, requested):
        """
        The invariant, stated once. A leading slash is stripped rather than refused,
        because `/index.html` is how a browser asks for the front page; what matters
        is that the result still lands inside the build.
        """
        got = paths.resolve_within(root, requested)
        assert got is None or root.resolve() in got.parents or got == root.resolve()

    def test_a_symlink_out_of_the_tree_is_refused(self, root, tmp_path):
        link = root / "escape"
        try:
            link.symlink_to(tmp_path / "secret.txt")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks need a privilege this machine has not granted")
        assert paths.resolve_within(root, "escape") is None


class TestSlug:
    def test_it_carries_a_readable_prefix(self):
        assert paths.mint_slug("Live Face Capture SDK").startswith("live-face-capture-sdk-")

    def test_it_carries_128_bits_of_secret(self):
        assert len(paths.mint_slug("x").rsplit("-", 1)[1]) == 32

    def test_two_are_never_the_same(self):
        assert len({paths.mint_slug("same name") for _ in range(200)}) == 200

    @pytest.mark.parametrize("name", ["", "   ", "///", "!!!"])
    def test_a_nameless_project_still_gets_an_address(self, name):
        assert paths.mint_slug(name).startswith("site-")
