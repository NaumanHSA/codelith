"""
The linker.

Deterministic and LLM-free on purpose: a model cannot construct a path to a page
that does not exist yet, and a documentation site with dead links reads as broken
however good its prose is. Every case here is a way a reference can be wrong, and
what the reader sees instead.
"""

from __future__ import annotations

import pytest

from app.agents.composition.linker import LinkerAgent

SITE_MAP = {
    "title": "widgets",
    "sections": [
        {
            "slug": "api",
            "title": "API Reference",
            "pages": [
                {"slug": "endpoints", "title": "Endpoints"},
                {"slug": "schemas", "title": "Schemas"},
            ],
        },
        {
            "slug": "guides",
            "title": "Guides",
            # Deliberately collides with api/schemas, so a bare `[[schemas]]` is
            # ambiguous and must not resolve to either.
            "pages": [{"slug": "schemas", "title": "Working with schemas"}],
        },
    ],
}


@pytest.fixture
def agent() -> LinkerAgent:
    return LinkerAgent(db=None, job_id=1)  # type: ignore[arg-type]


@pytest.fixture
def index(agent: LinkerAgent) -> dict:
    return agent._index(SITE_MAP)


def link(agent: LinkerAgent, index: dict, markdown: str, address: str = "api/endpoints"):
    return agent._link_one(markdown, 7, index, {"address": address})


class TestIndex:
    def test_full_addresses_resolve(self, index) -> None:
        assert index["api/endpoints"]["title"] == "Endpoints"

    def test_an_unambiguous_bare_slug_resolves(self, index) -> None:
        """`[[endpoints]]` is what a model naturally writes."""
        assert index["endpoints"]["section_slug"] == "api"

    def test_an_ambiguous_bare_slug_does_not(self, index) -> None:
        """Guessing would link half the references to the wrong page."""
        assert "schemas" not in index


class TestResolution:
    def test_a_reference_becomes_a_real_route(self, agent, index) -> None:
        out, report = link(agent, index, "See [[api/schemas]] for the shapes.")

        assert out == "See [Schemas](/app/projects/7/docs/api/schemas) for the shapes."
        assert report["resolved"] == 1

    def test_link_text_can_be_overridden(self, agent, index) -> None:
        out, _ = link(agent, index, "See [[api/schemas|the schema reference]].")
        assert "[the schema reference](/app/projects/7/docs/api/schemas)" in out

    def test_an_unresolvable_reference_degrades_to_text(self, agent, index) -> None:
        """Shipping `[[webhooks]]` to a reader is worse than losing the link."""
        out, report = link(agent, index, "See [[webhooks]] for callbacks.")

        assert out == "See webhooks for callbacks."
        assert report["unresolved"] == ["webhooks"]

    def test_an_ambiguous_reference_is_reported_not_guessed(self, agent, index) -> None:
        out, report = link(agent, index, "See [[schemas]].")
        assert report["unresolved"] == ["schemas"]
        assert "[[" not in out

    def test_several_references_in_one_page(self, agent, index) -> None:
        out, report = link(
            agent,
            index,
            "[[api/schemas]] and [[guides/schemas]] and [[api/endpoints]]",
            address="guides/setup",
        )
        assert report["resolved"] == 3
        assert out.count("/app/projects/7/docs/") == 3

    def test_a_self_reference_is_not_counted_as_a_link(self, agent, index) -> None:
        """It produced no link, so reporting one would overstate what happened."""
        out, report = link(agent, index, "See [[api/endpoints]].", address="api/endpoints")

        assert out == "See Endpoints."
        assert report["resolved"] == 0
        assert report["unresolved"] == []

    def test_ordinary_markdown_links_are_untouched(self, agent, index) -> None:
        source = "See [the RFC](https://example.com/rfc) and `[[not a link]]`."
        out, _ = link(agent, index, source)
        assert "https://example.com/rfc" in out

    def test_a_page_does_not_link_to_itself(self, agent, index) -> None:
        """A link that goes nowhere is worse than the plain words."""
        out, _ = link(agent, index, "See [here](/app/projects/7/docs/api/endpoints).")
        assert out == "See here."


class TestAnchors:
    def test_a_live_anchor_survives(self, agent, index) -> None:
        source = "## Listing widgets\n\nSee [above](#listing-widgets)."
        out, report = link(agent, index, source)

        assert "[above](#listing-widgets)" in out
        assert report["dead_anchors"] == []

    def test_a_dead_anchor_degrades_to_text_and_is_reported(self, agent, index) -> None:
        source = "## Listing widgets\n\nSee [below](#creating-widgets)."
        out, report = link(agent, index, source)

        assert out.endswith("See below.")
        assert report["dead_anchors"] == ["creating-widgets"]

    def test_headings_inside_a_fence_are_not_headings(self, agent, index) -> None:
        source = "```\n## Fake heading\n```\n\nSee [it](#fake-heading)."
        out, report = link(agent, index, source)

        assert report["dead_anchors"] == ["fake-heading"]
        assert "(#fake-heading)" not in out

    def test_accented_headings_match_the_anchor_the_ui_stamps(self, agent, index) -> None:
        """
        The one rule that must agree across the language boundary: the studio folds
        accents when it stamps a heading id, so the linker has to fold them too or
        every such link is reported dead.
        """
        source = "## Café Déploiement\n\nSee [it](#cafe-deploiement)."
        _, report = link(agent, index, source)

        assert report["dead_anchors"] == []


class TestSourcePathLinks:
    """
    A markdown link whose href is a source path.

    Nothing checked these before C5. The wiki syntax was validated, heading anchors
    were validated, and a plain `[text](some/file.py)` went straight through to the
    reader as a dead link — C1 measured one page shipping nineteen of them.
    """

    def test_a_source_path_link_becomes_code(self, agent, index) -> None:
        source = "See [`TracerConfig`](neurosurfer/tracing/config.py) for the knobs."
        out, report = link(agent, index, source)

        assert out == "See `TracerConfig` for the knobs."
        assert report["source_links"] == ["neurosurfer/tracing/config.py"]

    def test_a_stray_backtick_inside_the_href_is_handled(self, agent, index) -> None:
        """Observed verbatim in job #4: the href carried an unclosed backtick."""
        source = "See [`TracerConfig`](`neurosurfer/tracing/config.py)."
        out, report = link(agent, index, source)

        assert out == "See `TracerConfig`."
        assert report["source_links"] == ["neurosurfer/tracing/config.py"]

    def test_bare_symbol_text_is_backticked(self, agent, index) -> None:
        source = "Call [load_config](app/config.py) first."
        out, _ = link(agent, index, source)

        assert out == "Call `load_config` first."

    def test_prose_link_text_keeps_its_words_and_names_the_file(self, agent, index) -> None:
        source = "Read [the configuration loader](app/config.py) for details."
        out, _ = link(agent, index, source)

        assert out == "Read the configuration loader (`app/config.py`) for details."

    def test_resolved_page_routes_are_left_alone(self, agent, index) -> None:
        """The demotion runs last, so it must not undo the linker's own work."""
        source = "See [[api/schemas]] for the shapes."
        out, report = link(agent, index, source)

        assert "/app/projects/7/docs/api/schemas" in out
        assert report["source_links"] == []

    def test_external_urls_and_anchors_survive(self, agent, index) -> None:
        source = "## Setup\n\n[docs](https://example.com) and [above](#setup)."
        out, report = link(agent, index, source)

        assert "(https://example.com)" in out
        assert "(#setup)" in out
        assert report["source_links"] == []

    def test_an_image_is_not_demoted(self, agent, index) -> None:
        """A rendered diagram is a real embed, not a mistaken file reference."""
        source = "![diagram](data:image/png;base64,iVBORw0KGgo=)"
        out, report = link(agent, index, source)

        assert out == source
        assert report["source_links"] == []
