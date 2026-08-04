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

    # ── What the user asked for ───────────────────────────────────────────────
    doc_types: list[str]
    output_formats: list[str]
    requires_human_review: bool

    # ── Planning ──────────────────────────────────────────────────────────────
    strategy: dict
    documentation_plan: dict          # doc_type → {title, sections[]}

    # ── Fan-out control (set per writer Send) ─────────────────────────────────
    current_doc_type: str

    # ── Generation ────────────────────────────────────────────────────────────
    generated_docs: Annotated[list[dict], operator.add]
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

    # ── Control ───────────────────────────────────────────────────────────────
    requires_review: bool
    error: str | None
