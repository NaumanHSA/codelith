import operator
from typing import Annotated, Any, TypedDict


class DocumentationState(TypedDict, total=False):
    # ── Input ─────────────────────────────────────────────────────────────────
    project: Any
    job: Any
    job_config: dict

    # ── Coordinator ───────────────────────────────────────────────────────────
    doc_types: list[str]
    output_formats: list[str]
    requires_human_review: bool

    # ── Planning ──────────────────────────────────────────────────────────────
    documentation_plan: dict

    # ── Analysis ──────────────────────────────────────────────────────────────
    ingestion_result: dict
    codebase: Any  # ParsedCodebase

    # ── Architecture ──────────────────────────────────────────────────────────
    architecture_map: dict  # {services, tech_stack, patterns, entry_points}

    # ── Strategy ──────────────────────────────────────────────────────────────
    strategy: dict  # {audiences, priorities, template_hints}

    # ── Fan-out control (set per-writer Send) ─────────────────────────────────
    current_doc_type: str

    # ── Generation (Annotated so parallel writer nodes accumulate) ────────────
    generated_docs: Annotated[list[dict], operator.add]

    # ── Diagrams ──────────────────────────────────────────────────────────────
    diagrams: list[dict]  # [{name, diagram_type, content}]

    # ── Review ────────────────────────────────────────────────────────────────
    review_results: list[dict]
    all_approved: bool
    human_approved: bool

    # ── Publishing ────────────────────────────────────────────────────────────
    saved_doc_ids: list[int]

    # ── Control ───────────────────────────────────────────────────────────────
    requires_review: bool
    error: str | None

    # ── Phase 2.5: per-job sandbox (JobSandbox instance) ──────────────────────
    sandbox: Any
    repo_path: str        # actual path of the cloned/local repo on disk

    # ── Phase 3: enriched ingestion context ───────────────────────────────────
    api_specs: list       # list[ParsedApiSpec] from OpenAPI parser
    infra_context: list   # list[ParsedInfra] from infra parser
