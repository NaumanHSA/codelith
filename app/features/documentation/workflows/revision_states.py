"""State for the revision graph."""

from typing import Any, TypedDict


class RevisionState(TypedDict, total=False):
    """
    A targeted edit to prose that already exists.

    A `TypedDict`, not a bare `dict`: with a plain `dict` schema LangGraph replaces
    the whole state with whatever a node returns rather than merging per key, so the
    first node to return `{"generated_docs": [...]}` silently dropped `project` and
    everything else — and the linker two nodes later failed on a `KeyError` that
    pointed nowhere near the cause.

    Nothing here is reduced. The reviser edits one page and returns one document, so
    unlike composition there is no fan-out to concatenate.
    """

    # ── Input ─────────────────────────────────────────────────────────────────
    project: Any
    job: Any
    job_config: dict
    sandbox: Any

    # ── The target ────────────────────────────────────────────────────────────
    #: The page being revised, already loaded — see `RevisionService.load_target`.
    page: dict
    #: `anchor_id` of the `##` being revised. Absent means the whole page.
    anchor: str | None
    #: What the reader asked for, verbatim.
    instructions: str
    #: Earlier completed turns against this same heading, oldest first.
    history: list[dict]

    # ── Evidence ──────────────────────────────────────────────────────────────
    kb_id: int | None
    commit_sha: str | None
    site_map: dict
    strategy: dict
    #: Pages this job claims, in the shape the publisher expects.
    pages: list[dict]

    # ── Output ────────────────────────────────────────────────────────────────
    #: Set only when the revision renamed its own heading, so the caller can
    #: re-key the conversation that was addressed to the old one.
    new_anchor: str | None
    generated_docs: list[dict]
    linked_docs: list[dict]
    saved_page_ids: list[int]
    error: str
