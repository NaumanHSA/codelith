"""
How much detail a page should go into.

Page length has one real lever — words per heading, multiplied by heading count — and
until now it was a setting the operator changed once, globally, in `.env`. That is the
wrong shape for the decision: the same project wants a short *Getting started* and a
thorough *API reference*, and the person who knows which is which is the one asking
for the page, at the moment they ask for it.

**Three levels, not a number.** A words-per-heading field would be the honest
representation of the mechanism and the wrong thing to offer: nobody knows whether
they want 240 or 300, and the number is not what they are choosing. They are choosing
between "remind me how this works" and "I am going to implement against this".

Each level moves two things and says one thing:

  * `words_scale` and `heading_delta` scale what `config.py` already holds, so an
    operator who has tuned `SITE_WORDS_PER_HEADING` keeps their centre and still gets
    a spread around it.
  * `guidance` goes into the writer's prompt, because scaling a budget the model is
    already inclined to overshoot does not by itself change how it writes. The
    instruction is what changes the shape of the prose; the number bounds it.

Standard is exactly what `config.py` says, so the default behaviour is unchanged and
this is additive rather than a re-tuning of every existing page.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Depth(StrEnum):
    """How much a page should say. Ordered shortest to longest."""

    CONCISE = "concise"
    STANDARD = "standard"
    DETAILED = "detailed"


@dataclass(frozen=True, slots=True)
class DepthProfile:
    """One level: what it does to the budget, and what it tells the writer."""

    depth: Depth
    #: Multiplies `SITE_WORDS_PER_HEADING`.
    words_scale: float
    #: Added to `SITE_MAX_HEADINGS_PER_PAGE`, floored at 2 — a page with one heading
    #: is not a page, it is a paragraph with a title.
    heading_delta: int
    #: One line for the writer's prompt. Empty for standard: the prompt already says
    #: what a standard page is, and repeating it in different words is how prompts
    #: acquire contradictions.
    guidance: str
    #: What the studio shows.
    label: str
    blurb: str


_PROFILES: dict[Depth, DepthProfile] = {
    Depth.CONCISE: DepthProfile(
        depth=Depth.CONCISE,
        words_scale=0.5,
        heading_delta=-2,
        guidance=(
            "This page is deliberately brief. Give the shortest explanation that is "
            "still correct and still checkable: what this is, how it is used, and the "
            "one thing a reader would get wrong. Name real symbols and paths so they "
            "can go and look, and then stop — leave the exhaustive treatment to the "
            "source. Do not list every option, parameter or edge case."
        ),
        label="Concise",
        blurb="What it is, how to use it, and the one thing people get wrong.",
    ),
    Depth.STANDARD: DepthProfile(
        depth=Depth.STANDARD,
        words_scale=1.0,
        heading_delta=0,
        guidance="",
        label="Standard",
        blurb="The working middle. Enough to use the code without reading it.",
    ),
    Depth.DETAILED: DepthProfile(
        depth=Depth.DETAILED,
        words_scale=1.75,
        heading_delta=2,
        guidance=(
            "This page is a reference someone will implement against. Cover the "
            "parameters, the return shapes, the failure modes and the edge cases, and "
            "show a worked example drawn from the supplied source. Depth means more "
            "*material* — more of what the code actually does — never the same claim "
            "restated at greater length."
        ),
        label="Detailed",
        blurb="A reference to implement against: parameters, failures, examples.",
    ),
}

#: The values the API accepts. Kept next to the definitions so the schema's `Literal`
#: has something to be checked against — see `tests/unit/apps/test_depth.py`.
VALUES: tuple[str, ...] = tuple(d.value for d in Depth)

DEFAULT = Depth.STANDARD


def profile(value: str | None) -> DepthProfile:
    """
    The profile for a name, falling back to standard.

    Never raises. An unknown value reaching here means a job row written by an older
    version, or a caller that has not been updated — and the right answer to "I do not
    recognise this depth" is a normal page, not a failed composition ten minutes in.
    """
    try:
        return _PROFILES[Depth(str(value or "").strip().lower())]
    except (KeyError, ValueError):
        return _PROFILES[DEFAULT]


def words_per_heading(value: str | None, configured: int) -> int:
    """Scaled against the operator's own setting, never below 80."""
    return max(80, round(configured * profile(value).words_scale))


def max_headings(value: str | None, configured: int) -> int:
    """Shifted against the operator's own cap, never below 2."""
    return max(2, configured + profile(value).heading_delta)


def choices() -> list[dict]:
    """What the studio renders, in order. The API serves this so the two cannot drift."""
    return [
        {"id": p.depth.value, "label": p.label, "blurb": p.blurb}
        for p in (_PROFILES[d] for d in Depth)
    ]


__all__ = [
    "DEFAULT",
    "Depth",
    "DepthProfile",
    "VALUES",
    "choices",
    "max_headings",
    "profile",
    "words_per_heading",
]
