"""
The build itself: files on disk, and the check that decides whether they may be served.

The renderer is exercised against the real `StaticSiteFormatter` rather than a stub,
because the thing worth proving is that publishing and exporting produce the same
site. A stub would prove only that the wrapper calls something.

The verifier is exercised against directories built by hand, because its whole job is
to catch output a renderer got wrong, and a renderer that got it right cannot
demonstrate that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codelith.apps.documentation.formatters.site_tree import (
    ExportPage,
    ExportSection,
    SiteTree,
)
from codelith.apps.documentation.publishing.renderers import (
    DEFAULT_RENDERER,
    BuiltinRenderer,
    available_renderers,
    get_renderer,
)
from codelith.apps.documentation.publishing.verify import verify_build


def _tree():
    return SiteTree(
        title="Neurosurfer",
        sections=[
            ExportSection(
                slug="guides",
                title="Guides",
                pages=[
                    ExportPage(
                        section_slug="guides", slug="getting-started",
                        title="Getting started", content_markdown="# Getting started\n\nRun it.",
                        order_index=0, intent=None, commit_sha="4865c2f", source_files=["a.py"],
                    ),
                    ExportPage(
                        section_slug="guides", slug="architecture",
                        title="Architecture", content_markdown="# Architecture\n\nParts.",
                        order_index=1, intent=None, commit_sha="4865c2f", source_files=[],
                    ),
                ],
            )
        ],
        home_markdown="# Neurosurfer\n\nWelcome.",
        version_label=None,
    )


class TestBuiltinRenderer:
    def test_it_is_always_available(self):
        """No dependency, no external tool, so there is no machine it cannot run on."""
        ok, reason = BuiltinRenderer().available()
        assert ok and reason == ""

    def test_it_is_the_default(self):
        assert get_renderer(None).name == DEFAULT_RENDERER

    def test_an_unknown_renderer_raises_rather_than_falling_back(self):
        with pytest.raises(KeyError):
            get_renderer("nope")

    def test_it_reports_itself_as_available(self):
        assert any(r["name"] == "builtin" and r["available"] for r in available_renderers())

    def test_it_writes_a_page_per_page_plus_the_index(self, tmp_path):
        result = BuiltinRenderer().build(_tree(), tmp_path)
        html = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.html"))
        assert "index.html" in html
        assert result.page_count == 2
        assert result.file_count == len(list(p for p in tmp_path.rglob("*") if p.is_file()))
        assert result.bytes_total == sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file())

    def test_the_prose_reaches_the_html(self, tmp_path):
        BuiltinRenderer().build(_tree(), tmp_path)
        joined = "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.html"))
        assert "Getting started" in joined
        assert "Architecture" in joined

    def test_what_it_builds_passes_its_own_verification(self, tmp_path):
        """
        The one test that ties the two halves together. If the shipped renderer
        produced a site the shipped verifier refuses, publishing could never succeed.
        """
        BuiltinRenderer().build(_tree(), tmp_path)
        report = verify_build(tmp_path)
        assert report.ok, f"broken={report.broken} external={report.external}"
        assert report.links_checked > 0

    def test_it_reaches_nothing_outside_the_machine(self, tmp_path):
        """The product's central claim, asserted against its own output."""
        BuiltinRenderer().build(_tree(), tmp_path)
        assert verify_build(tmp_path).external == []


class TestVerifier:
    def _site(self, root: Path, html: str, *, css: str | None = None) -> Path:
        (root / "index.html").write_text(html, encoding="utf-8")
        if css is not None:
            (root / "assets").mkdir(exist_ok=True)
            (root / "assets" / "theme.css").write_text(css, encoding="utf-8")
        return root

    def test_a_working_link_passes(self, tmp_path):
        (tmp_path / "other.html").write_text("<p>ok</p>")
        self._site(tmp_path, '<a href="other.html">go</a>')
        report = verify_build(tmp_path)
        assert report.ok and report.links_checked == 1

    def test_a_dead_link_fails(self, tmp_path):
        self._site(tmp_path, '<a href="missing.html">go</a>')
        report = verify_build(tmp_path)
        assert not report.ok and len(report.broken) == 1

    def test_a_missing_stylesheet_fails(self, tmp_path):
        self._site(tmp_path, '<link href="assets/theme.css" rel="stylesheet">')
        assert not verify_build(tmp_path).ok

    @pytest.mark.parametrize(
        "ref",
        [
            "https://fonts.googleapis.com/css2?family=Inter",
            "http://cdn.example.com/x.js",
            "//cdn.jsdelivr.net/npm/thing",
        ],
    )
    def test_anything_off_the_machine_fails(self, tmp_path, ref):
        self._site(tmp_path, f'<link href="{ref}" rel="stylesheet">')
        report = verify_build(tmp_path)
        assert not report.ok and len(report.external) == 1

    def test_a_web_font_hiding_in_css_is_caught(self, tmp_path):
        """
        The realistic version of this failure. Nobody puts a CDN link in the HTML by
        hand; a theme puts one in its stylesheet, three levels down.
        """
        self._site(
            tmp_path,
            '<link href="assets/theme.css" rel="stylesheet">',
            css="@font-face{src:url(https://fonts.gstatic.com/s/inter.woff2)}",
        )
        report = verify_build(tmp_path)
        assert not report.ok and report.external

    @pytest.mark.parametrize("ref", ["#section", "data:image/svg+xml;base64,PHN2Zy8+", "mailto:a@b.c"])
    def test_local_references_are_left_alone(self, tmp_path, ref):
        self._site(tmp_path, f'<a href="{ref}">x</a>')
        assert verify_build(tmp_path).ok

    def test_a_directory_link_resolves_through_its_index(self, tmp_path):
        (tmp_path / "guides").mkdir()
        (tmp_path / "guides" / "index.html").write_text("<p>ok</p>")
        self._site(tmp_path, '<a href="guides/">go</a>')
        assert verify_build(tmp_path).ok

    def test_the_report_caps_what_it_stores(self, tmp_path):
        """A systematically broken build must not write thousands of strings into JSON."""
        self._site(tmp_path, "".join(f'<a href="gone{i}.html">x</a>' for i in range(200)))
        d = verify_build(tmp_path).as_dict()
        assert d["broken_total"] == 200 and len(d["broken"]) == 50


class TestLinksToUnwrittenPages:
    """
    The bug publishing found on its first real site.

    Two pages written, nineteen still planned, and the prose of the written two linked
    to the planned ones. Export drops unwritten pages but kept the links to them, so
    every archive shipped with dead hrefs: twenty-two of them, unnoticed, because
    nobody link-checks a ZIP they just downloaded.
    """

    def _linking_tree(self):
        body = (
            "See [ONNX runtime](/app/projects/1/docs/utilities/onnx-runtime) "
            "and [Installation](/app/projects/1/docs/guides/install)."
        )
        return SiteTree(
            title="Site",
            sections=[
                ExportSection(
                    slug="guides",
                    title="Guides",
                    pages=[
                        ExportPage(
                            section_slug="guides", slug="intro", title="Intro",
                            content_markdown=body, order_index=0, intent=None,
                            commit_sha=None, source_files=[],
                        ),
                        ExportPage(
                            section_slug="guides", slug="install", title="Installation",
                            content_markdown="# Installation", order_index=1, intent=None,
                            commit_sha=None, source_files=[],
                        ),
                    ],
                )
            ],
            home_markdown="# Site",
            version_label=None,
        )

    def test_a_site_that_links_to_unwritten_pages_still_verifies(self, tmp_path):
        BuiltinRenderer().build(self._linking_tree(), tmp_path)
        report = verify_build(tmp_path)
        assert report.ok, f"broken={report.broken}"

    def test_the_link_becomes_its_own_text(self, tmp_path):
        BuiltinRenderer().build(self._linking_tree(), tmp_path)
        page = next(p for p in tmp_path.rglob("*.html") if "intro" in p.name)
        html = page.read_text(encoding="utf-8")
        assert "ONNX runtime" in html, "the sentence must still read"
        assert "onnx-runtime.html" not in html, "but must not promise a page that is absent"

    def test_a_link_to_a_page_that_exists_survives(self, tmp_path):
        BuiltinRenderer().build(self._linking_tree(), tmp_path)
        page = next(p for p in tmp_path.rglob("*.html") if "intro" in p.name)
        assert "install.html" in page.read_text(encoding="utf-8")


class TestDiagrams:
    """
    Diagrams arrive as `data:image/svg+xml;base64,…` and used to render as a
    screenful of their own base64.

    `markdown-it`'s link validator allows a `data:` image for png, gif, jpeg and webp
    and refuses it for svg, because an SVG data URI can carry script. The refusal is
    silent: the image falls back to literal text. Writing each one out as a file
    sidesteps the validator, and is safe for the reason the validator exists — an SVG
    loaded through `<img src>` cannot execute script.
    """

    #: A real, tiny SVG, base64 encoded.
    SVG = (
        "data:image/svg+xml;base64,"
        "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMCIgaGVpZ2h0PSIxMCIvPg=="
    )

    def _tree_with_diagram(self, body=None):
        return SiteTree(
            title="Site",
            sections=[
                ExportSection(
                    slug="guides", title="Guides",
                    pages=[
                        ExportPage(
                            section_slug="guides", slug="arch", title="Architecture",
                            content_markdown=body or f"## Diagrams\n\n![System Context]({self.SVG})\n",
                            order_index=0, intent=None, commit_sha=None, source_files=[],
                        )
                    ],
                )
            ],
            home_markdown="# Site",
            version_label=None,
        )

    def test_the_diagram_becomes_a_file(self, tmp_path):
        BuiltinRenderer().build(self._tree_with_diagram(), tmp_path)
        svgs = list((tmp_path / "assets" / "diagrams").glob("*.svg"))
        assert len(svgs) == 1
        assert svgs[0].read_bytes().startswith(b"<svg")

    def test_the_page_shows_an_image_not_its_source(self, tmp_path):
        BuiltinRenderer().build(self._tree_with_diagram(), tmp_path)
        page = next(p for p in tmp_path.rglob("*.html") if "arch" in p.name)
        html = page.read_text(encoding="utf-8")
        assert "<img" in html and "assets/diagrams/" in html
        assert "base64" not in html, "the source must not be sitting in the page"

    def test_the_reference_resolves(self, tmp_path):
        """The whole point: a diagram that verification accepts."""
        BuiltinRenderer().build(self._tree_with_diagram(), tmp_path)
        report = verify_build(tmp_path)
        assert report.ok, f"broken={report.broken}"

    def test_the_same_diagram_twice_is_stored_once(self, tmp_path):
        body = f"![One]({self.SVG})\n\n![Two again]({self.SVG})\n"
        BuiltinRenderer().build(self._tree_with_diagram(body), tmp_path)
        assert len(list((tmp_path / "assets" / "diagrams").glob("*.svg"))) == 1

    def test_a_corrupt_data_uri_does_not_take_the_build_down(self, tmp_path):
        BuiltinRenderer().build(
            self._tree_with_diagram("![Broken](data:image/svg+xml;base64,not!valid!)\n"), tmp_path
        )
        assert list(tmp_path.rglob("*.html")), "the page still exists"

    def test_the_diagram_source_block_is_dropped(self, tmp_path):
        """A published site has readers, not authors. D2 source is noise to all of them."""
        body = (
            f"![System Context]({self.SVG})\n\n"
            "<details>\n<summary>Diagram source</summary>\n\n"
            "```d2\na -> b\n```\n\n</details>\n"
        )
        BuiltinRenderer().build(self._tree_with_diagram(body), tmp_path)
        html = next(p for p in tmp_path.rglob("*.html") if "arch" in p.name).read_text(encoding="utf-8")
        assert "Diagram source" not in html
        assert "a -&gt; b" not in html and "a -> b" not in html


class TestPublishedNavigation:
    """The studio's shape: tabs, a rail for the open section, headings on the right."""

    def _two_sections(self):
        def page(section, slug, title, body):
            return ExportPage(
                section_slug=section, slug=slug, title=title, content_markdown=body,
                order_index=0, intent=None, commit_sha=None, source_files=[],
            )
        return SiteTree(
            title="Site",
            sections=[
                ExportSection(slug="start", title="Getting Started", pages=[
                    page("start", "intro", "Intro", "## Core\n\ntext\n\n### Detail\n\nmore\n")]),
                ExportSection(slug="testing", title="Testing", pages=[
                    page("testing", "suites", "Test Suites", "## Suites\n\ntext\n")]),
            ],
            home_markdown="# Site",
            version_label=None,
        )

    def _page(self, tmp_path, name):
        BuiltinRenderer().build(self._two_sections(), tmp_path)
        return next(p for p in tmp_path.rglob("*.html") if name in p.name).read_text(encoding="utf-8")

    def test_both_sections_are_tabs(self, tmp_path):
        html = self._page(tmp_path, "intro")
        tabs = html.split('<nav class="tabs">')[1].split("</nav>")[0]
        assert "Getting Started" in tabs and "Testing" in tabs and "Overview" in tabs

    def test_the_rail_holds_only_the_open_section(self, tmp_path):
        """
        The bug this replaces: every page of every section in one flat list, so
        Getting Started and Testing sat together as though they were one thing.
        """
        html = self._page(tmp_path, "intro")
        rail = html.split('<aside class="left">')[1].split("</aside>")[0]
        assert "Intro" in rail
        assert "Test Suites" not in rail

    def test_headings_fill_the_right_rail(self, tmp_path):
        html = self._page(tmp_path, "intro")
        right = html.split('<aside class="right">')[1].split("</aside>")[0]
        assert "On this page" in right
        assert 'href="#core"' in right and 'href="#detail"' in right

    def test_the_open_tab_is_marked(self, tmp_path):
        html = self._page(tmp_path, "suites")
        tabs = html.split('<nav class="tabs">')[1].split("</nav>")[0]
        assert 'class="tab on" href="../testing/suites.html">Testing' in tabs

    def test_the_chrome_is_there(self, tmp_path):
        html = self._page(tmp_path, "intro")
        assert 'class="brand"' in html and "code<i>·</i>lith" in html
        assert 'class="theme"' in html, "the light/dark toggle"
        assert "<footer>" in html and "Codelith" in html

    def test_the_theme_is_applied_before_the_first_paint(self, tmp_path):
        """A toggle that flashes the wrong theme on every navigation is worse than none."""
        html = self._page(tmp_path, "intro")
        head = html.split("</head>")[0]
        assert "localStorage.getItem('codelith-theme')" in head
