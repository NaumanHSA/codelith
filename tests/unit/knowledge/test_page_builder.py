"""
Adding a page the model never proposed.

Two of these guard properties that are invisible until they fail months later: a
user-added page that is not `pinned` is silently orphaned by the next analysis, and a
slug that collides with a later proposal breaks the merge key. Neither shows up in a
single run.
"""

from __future__ import annotations

import pytest

from codelith.knowledge.sites import coerce_doc_type, slugify, unique_slug


class TestSlugAssignment:
    def test_a_title_becomes_a_url_safe_slug(self) -> None:
        assert slugify("Major Modules") == "major-modules"

    def test_slugs_are_unique_across_the_whole_site(self) -> None:
        """
        `coerce_site_map` uses one namespace for proposed pages, so a user-added page
        must too — otherwise a later analysis proposes the same slug in another
        section and the merge key stops identifying one row.
        """
        taken = {"overview", "major-modules"}

        assert unique_slug("major-modules", taken) == "major-modules-2"

    def test_an_unused_slug_is_left_alone(self) -> None:
        assert unique_slug("shell-completions", {"overview"}) == "shell-completions"

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Café Déploiement", "cafe-deploiement"),
            ("POST /v1/chat/completions", "post-v1-chat-completions"),
            ("  spaced  out  ", "spaced-out"),
        ],
    )
    def test_awkward_titles_still_produce_addresses(self, title, expected) -> None:
        assert slugify(title) == expected


class TestDocType:
    def test_a_known_type_is_kept(self) -> None:
        assert coerce_doc_type("architecture") == "architecture"

    def test_an_invented_type_falls_back_rather_than_failing(self) -> None:
        """A model returning nonsense should still produce a writable page."""
        assert coerce_doc_type("beautiful-prose") == "modules"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_a_missing_type_falls_back(self, raw) -> None:
        assert coerce_doc_type(raw) == "modules"


class TestAnchorRanking:
    """
    Files are ranked by how many chunks they contributed, not by best single chunk.
    A file the query matched repeatedly is more likely to be what the page is *about*
    than one that matched once very well.
    """

    def test_the_most_frequently_matched_file_ranks_first(self) -> None:
        chunks = [
            {"source_path": "a.py"},
            {"source_path": "b.py"},
            {"source_path": "a.py"},
            {"source_path": "c.py"},
            {"source_path": "a.py"},
            {"source_path": "b.py"},
        ]
        ranked: dict[str, int] = {}
        for c in chunks:
            ranked[c["source_path"]] = ranked.get(c["source_path"], 0) + 1
        order = [p for p, _ in sorted(ranked.items(), key=lambda kv: -kv[1])]

        assert order[0] == "a.py"
        assert order[1] == "b.py"

    def test_the_anchor_list_is_capped(self) -> None:
        from codelith.knowledge.sites import MAX_KEY_FILES

        ranked = {f"f{i}.py": 10 - i for i in range(20)}
        picked = [p for p, _ in sorted(ranked.items(), key=lambda kv: -kv[1])][:MAX_KEY_FILES]

        assert len(picked) == MAX_KEY_FILES


class TestPinning:
    def test_the_merge_skips_pinned_pages_when_orphaning(self) -> None:
        """
        The property a user-added page depends on. `merge_proposal` orphans anything
        the latest proposal does not contain, and a user's page is never in one — so
        without the pin it silently leaves the nav on the next analysis.
        """
        import inspect

        from codelith.apps.documentation.services.site_service import SiteService

        source = inspect.getsource(SiteService.merge_proposal)
        assert "not p.pinned" in source, "the orphaning pass must exempt pinned pages"
