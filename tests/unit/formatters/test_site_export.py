"""
Export targets, given a real page tree for the first time.

MkDocs and Docusaurus existed long before pages did, so both flattened a project
into one file per document type with a hand-written nav. What is verified here is
the thing they never had: a directory per section, a generated nav in the site's own
order, and cross-page links that still resolve once the studio's routes are gone.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
import yaml

from codelith.apps.documentation.formatters.docusaurus import DocusaurusFormatter
from codelith.apps.documentation.formatters.mkdocs import MkDocsFormatter
from codelith.apps.documentation.formatters.site_tree import (
    ExportPage,
    ExportSection,
    SiteTree,
    rewrite_links,
)
from codelith.apps.documentation.formatters.static_site import StaticSiteFormatter


def page(section: str, slug: str, title: str, body: str = "Prose.") -> ExportPage:
    return ExportPage(
        section_slug=section,
        slug=slug,
        title=title,
        content_markdown=body,
        intent=f"Covers {title}.",
        commit_sha="4065c2f1",
        source_files=["app/api/routes.py"],
    )


@pytest.fixture
def tree() -> SiteTree:
    return SiteTree(
        title="widgets",
        home_markdown="A widget service.",
        sections=[
            ExportSection(
                slug="api",
                title="API Reference",
                pages=[
                    page(
                        "api", "endpoints", "Endpoints",
                        "See [Schemas](/app/projects/7/docs/api/schemas) and "
                        "[Setup](/app/projects/7/docs/guides/setup#install).",
                    ),
                    page("api", "schemas", "Schemas"),
                ],
            ),
            ExportSection(slug="guides", title="Guides", pages=[page("guides", "setup", "Setup")]),
            # Nothing written: must not become an empty nav entry anywhere.
            ExportSection(
                slug="empty",
                title="Empty",
                pages=[ExportPage("empty", "todo", "Todo", content_markdown="")],
            ),
        ],
    )


def names(data: bytes) -> set[str]:
    return set(zipfile.ZipFile(io.BytesIO(data)).namelist())


def read(data: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read(name).decode()


class TestLinkRewriting:
    """The counterpart to the linker: studio routes back into relative paths."""

    def test_a_link_within_a_section_is_a_sibling_file(self) -> None:
        out = rewrite_links(
            "[x](/app/projects/7/docs/api/schemas)", from_page="api/endpoints"
        )
        assert out == "[x](schemas.md)"

    def test_a_link_across_sections_goes_up_one(self) -> None:
        out = rewrite_links(
            "[x](/app/projects/7/docs/guides/setup)", from_page="api/endpoints"
        )
        assert out == "[x](../guides/setup.md)"

    def test_anchors_survive(self) -> None:
        out = rewrite_links(
            "[x](/app/projects/7/docs/api/schemas#fields)", from_page="api/endpoints"
        )
        assert out == "[x](schemas.md#fields)"

    def test_the_suffix_follows_the_target(self) -> None:
        source = "[x](/app/projects/7/docs/api/schemas)"
        assert rewrite_links(source, from_page="api/e", suffix=".html").endswith("schemas.html)")
        assert rewrite_links(source, from_page="api/e", suffix="").endswith("schemas)")

    def test_external_links_are_untouched(self) -> None:
        source = "[rfc](https://example.com/x) and [rel](../other.md)"
        assert rewrite_links(source, from_page="api/endpoints") == source


class TestMkDocs:
    def test_a_directory_per_section(self, tree) -> None:
        files = names(MkDocsFormatter().format_site_tree(tree))

        assert "docs/api/endpoints.md" in files
        assert "docs/api/schemas.md" in files
        assert "docs/guides/setup.md" in files
        assert "mkdocs.yml" in files

    def test_the_nav_is_nested_and_in_site_order(self, tree) -> None:
        """The thing this formatter was shaped for and never had."""
        config = yaml.safe_load(read(MkDocsFormatter().format_site_tree(tree), "mkdocs.yml"))

        assert config["site_name"] == "widgets"
        assert config["nav"][0] == {"Home": "index.md"}
        assert config["nav"][1] == {
            "API Reference": [
                {"Endpoints": "api/endpoints.md"},
                {"Schemas": "api/schemas.md"},
            ]
        }
        assert config["nav"][2] == {"Guides": [{"Setup": "guides/setup.md"}]}

    def test_an_unwritten_section_is_not_a_nav_entry(self, tree) -> None:
        """A nav entry opening onto "not written yet" is worse than one page fewer."""
        config = yaml.safe_load(read(MkDocsFormatter().format_site_tree(tree), "mkdocs.yml"))
        assert not any("Empty" in entry for entry in config["nav"])
        assert "docs/empty/todo.md" not in names(MkDocsFormatter().format_site_tree(tree))

    def test_links_are_rewritten_for_the_export(self, tree) -> None:
        body = read(MkDocsFormatter().format_site_tree(tree), "docs/api/endpoints.md")

        assert "(schemas.md)" in body
        assert "(../guides/setup.md#install)" in body
        assert "/app/projects/" not in body

    def test_the_index_lists_every_written_page(self, tree) -> None:
        index = read(MkDocsFormatter().format_site_tree(tree), "docs/index.md")

        assert "A widget service." in index
        assert "[Endpoints](api/endpoints.md)" in index
        assert "Todo" not in index


class TestDocusaurus:
    def test_a_category_per_section(self, tree) -> None:
        data = DocusaurusFormatter().format_site_tree(tree)

        assert "docs/api/_category_.json" in names(data)
        category = json.loads(read(data, "docs/api/_category_.json"))
        assert category == {"label": "API Reference", "position": 1}

    def test_the_sidebar_mirrors_the_site_order(self, tree) -> None:
        """Docusaurus would otherwise invent an alphabetical one."""
        js = read(DocusaurusFormatter().format_site_tree(tree), "sidebars.js")
        sidebar = json.loads(js[js.index("[") : js.rindex("]") + 1])

        assert sidebar[0] == "intro"
        assert sidebar[1]["label"] == "API Reference"
        assert sidebar[1]["items"] == ["api/endpoints", "api/schemas"]

    def test_pages_are_mdx_with_frontmatter(self, tree) -> None:
        body = read(DocusaurusFormatter().format_site_tree(tree), "docs/api/endpoints.mdx")

        assert body.startswith("---\ntitle: \"Endpoints\"")
        assert "sidebar_position: 1" in body

    def test_links_drop_the_extension(self, tree) -> None:
        body = read(DocusaurusFormatter().format_site_tree(tree), "docs/api/endpoints.mdx")
        assert "(schemas)" in body and "(../guides/setup#install)" in body


class TestStaticHtml:
    def test_it_is_a_page_per_file_plus_one_stylesheet(self, tree) -> None:
        files = names(StaticSiteFormatter().format_site_tree(tree))

        assert files == {
            "assets/theme.css",
            "index.html",
            "api/endpoints.html",
            "api/schemas.html",
            "guides/setup.html",
        }

    def test_nothing_is_loaded_from_the_network(self, tree) -> None:
        """The product's claim is that nothing leaves the machine."""
        data = StaticSiteFormatter().format_site_tree(tree)
        for name in names(data):
            body = read(data, name)
            assert "http://" not in body
            assert "https://" not in body
            assert "//cdn" not in body

    def test_markdown_becomes_html(self, tree) -> None:
        tree.sections[1].pages[0].content_markdown = "## Install\n\n- one\n- two\n"
        body = read(StaticSiteFormatter().format_site_tree(tree), "guides/setup.html")

        assert "<h2>Install</h2>" in body
        assert "<li>one</li>" in body

    def test_every_page_carries_the_whole_nav(self, tree) -> None:
        body = read(StaticSiteFormatter().format_site_tree(tree), "api/schemas.html")

        assert "API Reference" in body and "Guides" in body
        assert 'href="../guides/setup.html"' in body

    def test_prev_and_next_cross_sections(self, tree) -> None:
        body = read(StaticSiteFormatter().format_site_tree(tree), "api/schemas.html")

        assert "← Endpoints" in body
        assert "Setup →" in body

    def test_provenance_reaches_the_reader(self, tree) -> None:
        body = read(StaticSiteFormatter().format_site_tree(tree), "api/schemas.html")
        assert "Written from 1 file at 4065c2f" in body

    def test_links_point_at_html_files(self, tree) -> None:
        body = read(StaticSiteFormatter().format_site_tree(tree), "api/endpoints.html")

        assert 'href="schemas.html"' in body
        assert "/app/projects/" not in body
