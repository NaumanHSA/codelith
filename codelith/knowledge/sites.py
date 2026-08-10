"""
Site-map vocabulary: slugs, and turning a model's proposal into a canonical map.

A documentation site is one site per project, grown a section at a time. The map is
decided during analysis — `site_planner` proposes the whole thing — and built in
pieces by later composition jobs. That ordering only works if two rules hold, and
both live here:

**Slugs are URLs.** A page slug is assigned once, from its first title, and pinned
forever. Renaming one breaks a bookmark, an internal `[[page-slug]]` link and the
provenance trail that says which commit a page was written from. So `slugify` is
deterministic, ASCII-only and bounded, and `unique_slug` resolves collisions by
suffix rather than by re-deriving from a different title.

**The vocabulary stays closed.** `doc_type` selects which narratives a page is
written from (`topics_for_doc_type`) and which modules its planner is shown
(`_ROLE_FOCUS`). A model that invents `"api_reference"` would silently get the
default mapping for both, so proposals are coerced onto the known set instead —
the same guard `coerce_topics` applies to narrative topics.

Nothing here touches the database. `SiteService.merge_proposal` owns what happens
when a canonical map meets the pages that already exist.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from codelith.knowledge.narratives import DOC_TYPE_TOPICS

#: Doc types a page may claim. Keyed to the narrative mapping because that is what
#: consumes it — a type absent from there reads no narratives at all.
KNOWN_DOC_TYPES: frozenset[str] = frozenset(DOC_TYPE_TOPICS)

#: Where an unrecognised doc type lands. `modules` is the generic "document this
#: part of the code" type, so a coerced page is still written from something sane.
DEFAULT_DOC_TYPE = "modules"

#: Human labels for the sections the deterministic fallback builds.
SECTION_LABELS: dict[str, str] = {
    "architecture": "Architecture",
    "api": "API Reference",
    "getting_started": "Getting Started",
    "deployment": "Deployment",
    "modules": "Modules",
    "testing": "Testing",
}

#: Slugs are path segments in a URL; anything longer is a scroll bar, not an address.
MAX_SLUG_CHARS = 64
#: Pages carry their intent into every downstream prompt, so it stays a sentence.
MAX_INTENT_CHARS = 300
#: Matches the composition planner: more anchor files than this dilutes retrieval.
MAX_KEY_FILES = 5

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, fallback: str = "page") -> str:
    """
    A stable, URL-safe slug for a title.

    Deterministic and ASCII-folded on purpose: the same title must produce the same
    slug on every machine and every re-analysis, or the merge below inserts a
    duplicate page instead of recognising the one it already has.
    """
    folded = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = _NON_SLUG.sub("-", ascii_only).strip("-")
    if len(slug) > MAX_SLUG_CHARS:
        # Cut at a word boundary where there is one, so the slug still reads.
        slug = slug[:MAX_SLUG_CHARS].rsplit("-", 1)[0] or slug[:MAX_SLUG_CHARS]
    return slug or fallback


def anchor_id(text: str) -> str:
    """
    The id a heading gets in the rendered page.

    Same rule as `slugify` minus the length cap, because this is a URL *fragment*
    and truncating it would stop it matching the anchor the reader actually renders.
    It has to agree exactly with `anchorId` in `ui/src/app/lib/site.ts` — the studio
    stamps these ids onto headings, and the linker validates links against them, so
    a divergence turns every long or accented heading link into a dead one.
    """
    folded = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = folded.encode("ascii", "ignore").decode("ascii").lower()
    return _NON_SLUG.sub("-", ascii_only).strip("-")


def unique_slug(base: str, taken: set[str]) -> str:
    """
    `base`, or the first free `base-2`, `base-3`, … .

    Suffixing rather than re-deriving keeps the first page of a colliding pair on
    the slug it already had — which is the whole point of pinning them.
    """
    if base not in taken:
        return base
    for n in range(2, 100):
        candidate = f"{base}-{n}"
        if candidate not in taken:
            return candidate
    raise ValueError(f"could not find a free slug for {base!r}")


def coerce_doc_type(raw: Any) -> str:
    """Map a proposed doc type onto the known set, defaulting rather than dropping."""
    key = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in KNOWN_DOC_TYPES else DEFAULT_DOC_TYPE


def coerce_site_map(
    raw: Any,
    *,
    known_files: set[str],
    fallback_title: str,
    max_sections: int,
    max_pages: int,
) -> dict:
    """
    A model's proposal, reduced to the canonical map the rest of the system reads.

    Everything unusable is discarded quietly: a section with no title, a page whose
    `key_files` name paths the knowledge base has never seen, a doc type nobody
    consumes. A hallucinated path is worth removing rather than warning about —
    downstream it retrieves nothing, and the page gets written from thin air.

    Returns `{"title", "sections": [{"slug", "title", "order_index", "pages": [...]}]}`
    with `sections` possibly empty, which callers treat as "the call failed".
    """
    if not isinstance(raw, dict):
        return {"title": fallback_title, "sections": []}

    title = str(raw.get("title") or "").strip() or fallback_title
    section_slugs: set[str] = set()
    page_slugs: set[str] = set()
    sections: list[dict] = []
    budget = max_pages

    for entry in raw.get("sections") or []:
        if len(sections) >= max_sections or budget <= 0:
            break
        if not isinstance(entry, dict):
            continue
        section_title = str(entry.get("title") or "").strip()
        if not section_title:
            continue
        slug = unique_slug(
            slugify(entry.get("slug") or section_title, fallback="section"), section_slugs
        )
        section_slugs.add(slug)

        pages = _coerce_pages(
            entry.get("pages"),
            known_files=known_files,
            # Slugs are unique per section, but the fallback map and the UI both read
            # better when they are unique across the site, so one namespace is used.
            taken=page_slugs,
            limit=budget,
        )
        if not pages:
            # A section with no pages is a nav entry that opens onto nothing.
            section_slugs.discard(slug)
            continue

        budget -= len(pages)
        sections.append(
            {
                "slug": slug,
                "title": section_title,
                "order_index": len(sections),
                "pages": pages,
            }
        )

    return {"title": title, "sections": sections}


def _coerce_pages(
    raw: Any, *, known_files: set[str], taken: set[str], limit: int
) -> list[dict]:
    pages: list[dict] = []
    for entry in raw or []:
        if len(pages) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        slug = unique_slug(slugify(entry.get("slug") or title), taken)
        taken.add(slug)
        pages.append(
            {
                "slug": slug,
                "title": title,
                "doc_type": coerce_doc_type(entry.get("doc_type")),
                "intent": str(entry.get("intent") or "").strip()[:MAX_INTENT_CHARS],
                "key_files": [
                    f for f in (entry.get("key_files") or []) if f in known_files
                ][:MAX_KEY_FILES],
                "confidence": _confidence(entry.get("confidence")),
                "reason": str(entry.get("reason") or "").strip()[:MAX_INTENT_CHARS],
                "order_index": len(pages),
            }
        )
    return pages


def _confidence(raw: Any) -> float:
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5


def derive_site_map(
    project_name: str,
    suggested_doc_types: list[dict],
    *,
    key_files_by_doc_type: dict[str, list[str]] | None = None,
    max_sections: int = 8,
) -> dict:
    """
    The fallback map, built from the doc-type suggestions analysis already computed.

    A failed planning call must cost site *quality*, not the site: without a map
    there is no nav, nothing to generate against, and the phase silently produces
    nothing. One section per evidence-backed doc type with a single overview page
    is thin, but it is real, and the merge treats it like any other proposal.
    """
    anchors = key_files_by_doc_type or {}
    sections: list[dict] = []
    for suggestion in suggested_doc_types[:max_sections]:
        doc_type = coerce_doc_type(suggestion.get("doc_type"))
        label = SECTION_LABELS.get(doc_type, doc_type.replace("_", " ").title())
        slug = slugify(doc_type, fallback="section")
        if any(s["slug"] == slug for s in sections):
            continue
        sections.append(
            {
                "slug": slug,
                "title": label,
                "order_index": len(sections),
                "pages": [
                    {
                        "slug": slug,
                        "title": label,
                        "doc_type": doc_type,
                        "intent": f"{label} for {project_name}.",
                        "key_files": anchors.get(doc_type, [])[:MAX_KEY_FILES],
                        "confidence": float(suggestion.get("confidence") or 0.5),
                        "reason": str(suggestion.get("reason") or "").strip(),
                        "order_index": 0,
                    }
                ],
            }
        )
    return {"title": project_name, "sections": sections}


def count_pages(site_map: dict) -> int:
    return sum(len(s.get("pages") or []) for s in (site_map or {}).get("sections") or [])


def doc_key(doc: dict) -> str:
    """
    What identifies one generated document to the stages after the writer.

    In page mode that is the page address; otherwise the doc type, as it always was.
    QA dedupes on it, diagrams are tagged with it, and the formatter names exports
    after it — all three of which silently collapse three `api` pages into one
    without it.
    """
    return str((doc or {}).get("address") or (doc or {}).get("doc_type") or "")


__all__ = [
    "DEFAULT_DOC_TYPE",
    "KNOWN_DOC_TYPES",
    "MAX_KEY_FILES",
    "SECTION_LABELS",
    "anchor_id",
    "coerce_doc_type",
    "coerce_site_map",
    "count_pages",
    "derive_site_map",
    "doc_key",
    "slugify",
    "unique_slug",
]
