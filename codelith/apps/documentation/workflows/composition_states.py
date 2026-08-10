"""State for the composition (Phase 2) graph."""

import operator
from typing import Annotated, Any, TypedDict


class CompositionState(TypedDict, total=False):
    """
    Seeded from a knowledge base, not from a repository.

    `generated_docs` is the only reduced key: writers fan out per document type and
    their results are concatenated. Every node must therefore return *only* the keys
    it changed — returning the whole state re-applies the reducer and doubles the list.
    """

    # ── Input ─────────────────────────────────────────────────────────────────
    project: Any
    job: Any
    job_config: dict
    sandbox: Any

    # ── Resolved knowledge base ───────────────────────────────────────────────
    kb_id: int
    kb_status: str
    kb_stats: dict
    #: Commit the knowledge base was built from — stamped onto every page written,
    #: which is what S5's staleness check diffs against.
    commit_sha: str | None
    #: Persisted by analysis, read back here. Diagrams are drawn from it.
    architecture_map: dict

    # ── What the user asked for ───────────────────────────────────────────────
    doc_types: list[str]
    #: Pages of the project's documentation site to write, resolved by `kb_loader`.
    #: Non-empty means page mode: the planner plans headings inside each page, the
    #: writer fans out per page, and the publisher writes `doc_pages`. Empty means
    #: the legacy one-flat-document-per-type path.
    pages: list[dict]
    #: The whole nav, carried into every page prompt so pages do not repeat each other.
    site_map: dict
    output_formats: list[str]
    requires_human_review: bool

    # ── Planning ──────────────────────────────────────────────────────────────
    strategy: dict
    #: doc_type → {title, sections[]}, or page address → {title, sections[]} in page
    #: mode. "Section" means a `##` heading either way, which is why one writer
    #: serves both: the level it operates at moved, not what it does.
    documentation_plan: dict

    # ── Fan-out control (set per writer Send) ─────────────────────────────────
    current_doc_type: str
    current_page: dict

    # ── Generation ────────────────────────────────────────────────────────────
    generated_docs: Annotated[list[dict], operator.add]
    #: `generated_docs` with `[[page-slug]]` references resolved to real routes.
    #: A plain list, not a reducer: the linker sees every page at once and rewrites
    #: the whole set, so appending would duplicate every page it touched.
    linked_docs: list[dict]
    link_report: list[dict]
    diagrams: list[dict]

    # ── Review ────────────────────────────────────────────────────────────────
    validation_results: list[dict]
    review_results: list[dict]
    all_approved: bool
    human_approved: bool

    # ── Publishing ────────────────────────────────────────────────────────────
    formatted_docs: list[dict]
    export_keys: dict
    saved_doc_ids: list[int]
    saved_page_ids: list[int]

    # ── Control ───────────────────────────────────────────────────────────────
    requires_review: bool
    error: str | None
