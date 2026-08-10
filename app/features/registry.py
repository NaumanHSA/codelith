"""
What a codebase unlocks once it has been read.

This repository was built documentation-first and named for it, and the shape stuck:
"analyse" read as a step on the way to producing a document. It never was. Analysis
takes no document type and never has, and Ask the Code proved the point by growing on
the same knowledge base without touching the documentation pipeline at all.

**A feature is defined by what it needs from the knowledge base.** That is the whole
contract. Documentation needs retrieval and narratives; Ask needs retrieval and the
code graph. Neither needs anything from the other, and neither may reach back into
analysis to ask for something special — if a feature wants a fact the KB does not
hold, the KB should hold it for everyone, which is a change to analysis made
deliberately rather than a special case bolted on for one consumer.

**One definition of availability, used everywhere.** Three services had each written
out `(READY, STALE, DEGRADED)` by hand and a fourth had drifted to `is_usable`, which
silently excludes `STALE` — so the same project could offer a feature on one screen
and refuse it on another. `KBStatus.can_serve_features` is now the single answer, and
this module is the single place that maps it onto what the studio should show.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.knowledge.constants import KBStatus


class FeatureState(StrEnum):
    """What the studio should render for one feature, on one project."""

    #: Built, and this project's knowledge base can serve it.
    AVAILABLE = "available"
    #: Built, but this project is not ready for it yet — analyse first.
    LOCKED = "locked"
    #: Not built. Shown so the shape of the product is legible, never clickable.
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class Feature:
    """One thing you can do with an analysed codebase."""

    id: str
    label: str
    #: One sentence, written for somebody deciding whether to click.
    blurb: str
    #: What it consumes from the knowledge base, in the KB's own vocabulary. This is
    #: documentation for a reader, not a dependency the code resolves — but it is the
    #: question to answer before adding a feature, so it is recorded next to it.
    needs: tuple[str, ...]
    #: Where the studio sends you. `{id}` is substituted with the project id.
    route: str
    #: False for something on the roadmap. A planned feature is a promise made inside
    #: the product, so this list stays short and honest.
    built: bool = True


#: Order is the order the studio renders them in.
FEATURES: tuple[Feature, ...] = (
    Feature(
        id="documentation",
        label="Documentation",
        blurb=(
            "Structured documents written from the analysis — Markdown, DOCX, MkDocs "
            "or Docusaurus. Document types are offered from what the code actually "
            "contains, so a project with no HTTP routes is never offered an API "
            "reference."
        ),
        needs=("retrieval", "narratives", "entities"),
        route="/app/projects/{id}/compose",
    ),
    Feature(
        id="ask",
        label="Ask the code",
        blurb=(
            "Ask a question and get an answer grounded in the source. Every citation "
            "is checked against the evidence actually retrieved, and one that does "
            "not resolve is stripped rather than shown."
        ),
        needs=("retrieval", "code graph", "entities"),
        route="/app/chat?project={id}&thread=new",
    ),
)

FEATURES_BY_ID = {f.id: f for f in FEATURES}


def state_for(feature: Feature, kb_status: str | None) -> tuple[FeatureState, str]:
    """
    `(state, reason)` for one feature against one project's knowledge base.

    The reason is shown to the reader, so it says what to do rather than what went
    wrong: a project that has never been analysed is not an error state, it is the
    first step nobody has taken yet.
    """
    if not feature.built:
        return FeatureState.PLANNED, "Not built yet."

    if kb_status is None:
        return FeatureState.LOCKED, "Analyse this repository to unlock it."

    status = KBStatus(kb_status)
    if status.can_serve_features:
        return FeatureState.AVAILABLE, ""

    if status in (KBStatus.PENDING, KBStatus.RUNNING):
        return FeatureState.LOCKED, "Analysis is still running."
    return FeatureState.LOCKED, "The last analysis failed. Run it again to unlock this."


def available_ids(kb_status: str | None) -> list[str]:
    """The features this knowledge base can currently serve."""
    return [f.id for f in FEATURES if state_for(f, kb_status)[0] is FeatureState.AVAILABLE]


__all__ = ["FEATURES", "FEATURES_BY_ID", "Feature", "FeatureState", "available_ids", "state_for"]
