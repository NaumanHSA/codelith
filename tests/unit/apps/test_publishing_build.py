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
