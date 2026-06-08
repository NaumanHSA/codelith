from typing import Any, TypedDict


class DocumentationState(TypedDict, total=False):
    # Input
    project: Any
    job: Any
    job_config: dict

    # Planning
    doc_types: list[str]
    output_formats: list[str]
    requires_human_review: bool
    documentation_plan: dict

    # Analysis
    ingestion_result: dict
    codebase: Any  # ParsedCodebase

    # Generation
    generated_docs: list[dict]  # [{doc_type, title, content_markdown}]

    # Review
    review_results: list[dict]
    all_approved: bool

    # Publishing
    saved_doc_ids: list[int]

    # Control flow
    requires_review: bool
    error: str | None
