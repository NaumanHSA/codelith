"""
What a codebase unlocks once it has been read.

This repository was built documentation-first and named for it, and the shape stuck:
"analyse" read as a step on the way to producing a document. It never was. Analysis
takes no document type and never has, and Ask the Code proved the point by growing on
the same knowledge base without touching the documentation pipeline at all.

**An app is defined by what it needs from the knowledge base.** That is the whole
contract. Documentation needs retrieval and narratives; Ask needs retrieval and the
code graph. Neither needs anything from the other, and neither may reach back into
analysis to ask for something special — if an app wants a fact the KB does not
hold, the KB should hold it for everyone, which is a change to analysis made
deliberately rather than a special case bolted on for one consumer.

**One definition of availability, used everywhere.** Three services had each written
out `(READY, STALE, DEGRADED)` by hand and a fourth had drifted to `is_usable`, which
silently excludes `STALE` — so the same project could offer an app on one screen
and refuse it on another. `KBStatus.can_serve_features` is now the single answer, and
this module is the single place that maps it onto what the studio should show.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from codelith.knowledge.constants import KBStatus


class AppState(StrEnum):
    """What the studio should render for one app, on one project."""

    #: Built, and this project's knowledge base can serve it.
    AVAILABLE = "available"
    #: Built, but this project is not ready for it yet — analyse first.
    LOCKED = "locked"
    #: Not built. Shown so the shape of the product is legible, never clickable.
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class App:
    """One thing you can do with an analysed codebase."""

    id: str
    label: str
    #: One sentence, written for somebody deciding whether to click.
    blurb: str
    #: The same thing in one line, for a card that sits beside two others rather than
    #: leading a page. Written rather than truncated: `blurb` cut at three lines stops
    #: mid-clause, and a sentence that ends is worth more than a longer one that
    #: trails off.
    short: str
    #: What it consumes from the knowledge base, in the KB's own vocabulary. This is
    #: documentation for a reader, not a dependency the code resolves — but it is the
    #: question to answer before adding an app, so it is recorded next to it.
    needs: tuple[str, ...]
    #: Where the studio sends you. `{id}` is substituted with the project id.
    route: str
    #: False for something on the roadmap. A planned app is a promise made inside
    #: the product, so this list stays short and honest.
    built: bool = True


#: Order is the order the studio renders them in.
APPS: tuple[App, ...] = (
    App(
        id="documentation",
        label="Documentation",
        blurb=(
            "Structured documents written from the analysis — Markdown, DOCX, MkDocs "
            "or Docusaurus. Document types are offered from what the code actually "
            "contains, so a project with no HTTP routes is never offered an API "
            "reference."
        ),
        short=(
            "Markdown, DOCX, MkDocs or Docusaurus, written from the analysis. Only the document types the code can actually support."
        ),
        needs=("retrieval", "narratives", "entities"),
        route="/app/projects/{id}/docs",
    ),
    App(
        id="ask",
        label="Ask the code",
        blurb=(
            "Ask a question and get an answer grounded in the source. Every citation "
            "is checked against the evidence actually retrieved, and one that does "
            "not resolve is stripped rather than shown."
        ),
        short=(
            "Answers grounded in the source, with every citation checked against what was actually retrieved."
        ),
        needs=("retrieval", "code graph", "entities"),
        route="/app/chat?project={id}&thread=new",
    ),
    App(
        id="drift",
        label="What changed",
        blurb=(
            "Compare two readings of the same repository and see what moved — modules "
            "added or rewritten, routes that came and went, and which written pages "
            "now describe code that is no longer there. Needs the codebase analysed "
            "twice; one reading is a photograph, two are a difference."
        ),
        short=(
            "What moved between two readings — and which written pages now describe code that is no longer there."
        ),
        needs=("modules", "entities", "written pages"),
        route="/app/projects/{id}/drift",
    ),
)

APPS_BY_ID = {f.id: f for f in APPS}


def state_for(app: App, kb_status: str | None) -> tuple[AppState, str]:
    """
    `(state, reason)` for one app against one project's knowledge base.

    The reason is shown to the reader, so it says what to do rather than what went
    wrong: a project that has never been analysed is not an error state, it is the
    first step nobody has taken yet.
    """
    if not app.built:
        return AppState.PLANNED, "Not built yet."

    if kb_status is None:
        return AppState.LOCKED, "Analyse this repository to unlock it."

    status = KBStatus(kb_status)
    if status.can_serve_features:
        return AppState.AVAILABLE, ""

    if status in (KBStatus.PENDING, KBStatus.RUNNING):
        return AppState.LOCKED, "Analysis is still running."
    return AppState.LOCKED, "The last analysis failed. Run it again to unlock this."


def available_ids(kb_status: str | None) -> list[str]:
    """The apps this knowledge base can currently serve."""
    return [f.id for f in APPS if state_for(f, kb_status)[0] is AppState.AVAILABLE]


__all__ = ["APPS", "APPS_BY_ID", "App", "AppState", "available_ids", "state_for"]
