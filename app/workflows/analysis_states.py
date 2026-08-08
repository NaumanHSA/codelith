"""State for the analysis (Phase 1) graph."""

from typing import Any, TypedDict


class AnalysisState(TypedDict, total=False):
    """
    Notice what is absent: no `doc_types`, no `output_formats`.

    Analysis runs before the user has chosen what to write, which is the point of the
    split — the knowledge base it produces serves any document type.

    No key here uses an `Annotated` reducer, so nodes must return only the keys they
    changed. Returning the whole state would be harmless today but becomes a
    doubling bug the moment an accumulator is added.
    """

    # ── Input ─────────────────────────────────────────────────────────────────
    project: Any
    job: Any
    sandbox: Any

    # ── Ingestion (repo_analyzer) ─────────────────────────────────────────────
    ingestion_result: dict
    codebase: Any          # ParsedCodebase
    repo_path: str
    api_specs: list
    infra_context: list

    # ── Knowledge base ────────────────────────────────────────────────────────
    kb_id: int
    commit_sha: str | None
    extraction_stats: dict

    # ── Semantic index ────────────────────────────────────────────────────────
    #: Node and edge counts from the code graph. Empty when Neo4j was unreachable —
    #: the run continues without it, so an empty dict is a real outcome, not an error.
    graph_stats: dict

    indexed_chunks: int
    embed_failures: int

    # ── Derived understanding ─────────────────────────────────────────────────
    summarised_modules: int
    summary_failures: int
    architecture_map: dict
    architecture_degraded: bool
    narratives_written: int
    narrative_failures: int

    # ── Documentation site ────────────────────────────────────────────────────
    # The map this analysis proposed, already merged into `doc_pages` by the time it
    # lands here. Carried so `kb_persister` can report coverage in the KB stats.
    site_map: dict
    site_pages: int
    site_degraded: bool

    # ── Outcome ───────────────────────────────────────────────────────────────
    kb_status: str
    kb_stats: dict
    error: str | None
