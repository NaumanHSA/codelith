"""
Slug rules and proposal coercion.

Slugs are URLs and are pinned forever, so the interesting cases here are all about
determinism: the same title must produce the same slug on every machine and every
re-analysis, and a model's proposal must never be able to smuggle in a path, a doc
type or a `key_files` entry that the rest of the system cannot honour.
"""

from __future__ import annotations

from app.knowledge.sites import (
    DEFAULT_DOC_TYPE,
    MAX_KEY_FILES,
    coerce_doc_type,
    coerce_site_map,
    count_pages,
    derive_site_map,
    slugify,
    unique_slug,
)


def page(**kw) -> dict:
    return {"title": "Endpoints", "doc_type": "api", **kw}


def proposal(*pages, title: str = "Docs", section: str = "API") -> dict:
    return {"title": title, "sections": [{"title": section, "pages": list(pages)}]}


def coerce(raw: dict, known: set[str] | None = None, **kw) -> dict:
    return coerce_site_map(
        raw,
        known_files=known if known is not None else {"a.py"},
        fallback_title="fallback",
        max_sections=kw.pop("max_sections", 8),
        max_pages=kw.pop("max_pages", 30),
    )


class TestSlugify:
    def test_it_is_url_safe(self) -> None:
        assert slugify("Getting Started!") == "getting-started"

    def test_accents_fold_to_ascii(self) -> None:
        """A slug is a path segment; percent-encoded UTF-8 is not an address."""
        assert slugify("Café Déploiement") == "cafe-deploiement"

    def test_it_is_deterministic(self) -> None:
        assert slugify("API Reference") == slugify("API  Reference ")

    def test_slashes_never_survive(self) -> None:
        """`section/page` is the address; a slug containing one would forge a level."""
        assert "/" not in slugify("api/v1/routes")

    def test_it_is_bounded(self) -> None:
        assert len(slugify("word " * 60)) <= 64

    def test_an_unusable_title_still_yields_a_slug(self) -> None:
        assert slugify("!!!") == "page"
        assert slugify("", fallback="section") == "section"


class TestUniqueSlug:
    def test_a_free_slug_is_returned_unchanged(self) -> None:
        assert unique_slug("endpoints", set()) == "endpoints"

    def test_collisions_are_suffixed_not_rederived(self) -> None:
        """The first page keeps the slug it had — that is what pinning means."""
        assert unique_slug("endpoints", {"endpoints"}) == "endpoints-2"
        assert unique_slug("endpoints", {"endpoints", "endpoints-2"}) == "endpoints-3"


class TestDocTypes:
    def test_a_known_type_survives(self) -> None:
        assert coerce_doc_type("getting_started") == "getting_started"

    def test_spelling_variants_are_normalised(self) -> None:
        assert coerce_doc_type("Getting-Started") == "getting_started"

    def test_an_invented_type_falls_back_rather_than_dropping_the_page(self) -> None:
        """`api_reference` would read no narratives at all; `modules` reads some."""
        assert coerce_doc_type("api_reference") == DEFAULT_DOC_TYPE


class TestCoerceSiteMap:
    def test_a_non_dict_proposal_is_an_empty_map(self) -> None:
        assert coerce("nonsense") == {"title": "fallback", "sections": []}  # type: ignore[arg-type]

    def test_key_files_are_validated_against_the_knowledge_base(self) -> None:
        """A hallucinated path retrieves nothing, so it is dropped before storage."""
        out = coerce(proposal(page(key_files=["a.py", "invented.py"])))
        assert out["sections"][0]["pages"][0]["key_files"] == ["a.py"]

    def test_key_files_are_capped(self) -> None:
        known = {f"f{i}.py" for i in range(10)}
        out = coerce(proposal(page(key_files=sorted(known))), known=known)
        assert len(out["sections"][0]["pages"][0]["key_files"]) == MAX_KEY_FILES

    def test_a_page_without_a_title_is_dropped(self) -> None:
        out = coerce(proposal(page(title=""), page(title="Schemas")))
        assert [p["title"] for p in out["sections"][0]["pages"]] == ["Schemas"]

    def test_a_section_with_no_usable_pages_is_dropped(self) -> None:
        """A nav entry that opens onto nothing is worse than no nav entry."""
        assert coerce(proposal(page(title="")))["sections"] == []

    def test_duplicate_titles_get_distinct_slugs(self) -> None:
        out = coerce(proposal(page(), page()))
        slugs = [p["slug"] for p in out["sections"][0]["pages"]]
        assert slugs == ["endpoints", "endpoints-2"]

    def test_the_page_budget_is_enforced_across_sections(self) -> None:
        raw = {
            "title": "Docs",
            "sections": [
                {"title": f"S{i}", "pages": [page(title=f"P{i}{j}") for j in range(3)]}
                for i in range(4)
            ],
        }
        assert count_pages(coerce(raw, max_pages=5)) == 5

    def test_the_section_budget_is_enforced(self) -> None:
        raw = {
            "title": "Docs",
            "sections": [{"title": f"S{i}", "pages": [page(title=f"P{i}")]} for i in range(6)],
        }
        assert len(coerce(raw, max_sections=2)["sections"]) == 2

    def test_confidence_is_clamped_and_defaulted(self) -> None:
        out = coerce(proposal(page(confidence="high"), page(title="B", confidence=7)))
        assert [p["confidence"] for p in out["sections"][0]["pages"]] == [0.5, 1.0]

    def test_order_index_follows_the_proposal(self) -> None:
        out = coerce(proposal(page(title="One"), page(title="Two")))
        assert [p["order_index"] for p in out["sections"][0]["pages"]] == [0, 1]

    def test_coercion_is_deterministic(self) -> None:
        raw = proposal(page(), page(title="Schemas"))
        assert coerce(raw) == coerce(raw)


class TestDerivedFallback:
    """A failed planning call must cost site quality, not the site."""

    def test_it_builds_a_section_per_suggested_doc_type(self) -> None:
        out = derive_site_map(
            "widgets",
            [{"doc_type": "api", "confidence": 0.9, "reason": "12 routes"},
             {"doc_type": "architecture", "confidence": 0.9, "reason": "45 modules"}],
        )
        assert [s["slug"] for s in out["sections"]] == ["api", "architecture"]
        assert count_pages(out) == 2

    def test_it_anchors_pages_on_real_files(self) -> None:
        out = derive_site_map(
            "widgets",
            [{"doc_type": "api", "confidence": 0.9, "reason": "r"}],
            key_files_by_doc_type={"api": ["app/api/routes.py"]},
        )
        assert out["sections"][0]["pages"][0]["key_files"] == ["app/api/routes.py"]

    def test_no_suggestions_means_no_sections(self) -> None:
        assert derive_site_map("widgets", [])["sections"] == []
