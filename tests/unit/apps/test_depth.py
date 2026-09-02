"""
How much a page says, and who gets to decide.

Page length had one lever — words per heading — and it was a global `.env` setting.
The same project wants a short *Getting started* and a thorough *API reference*, so
the decision belongs to the person asking for the page, at the moment they ask.

Two things are pinned here. The **arithmetic**, because a level that does not visibly
change the output is a control people stop trusting. And the **agreement between the
three places the levels are written down** — a Python profile table, a `Literal` in a
base schema that may not import it, and a TypeScript union in the studio. Three copies
that must say the same thing is exactly the shape that drifts silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from codelith.apps.documentation import depth as d
from codelith.schemas.knowledge import ComposeRequest

UI = Path(__file__).resolve().parents[3] / "ui" / "src" / "app"


class TestTheLevelsActuallyDiffer:
    def test_they_are_ordered_shortest_to_longest(self) -> None:
        """
        A control whose middle setting is not in the middle is a control that lies.
        """
        words = [d.words_per_heading(level, 350) for level in d.VALUES]
        headings = [d.max_headings(level, 6) for level in d.VALUES]

        assert words == sorted(words), words
        assert headings == sorted(headings), headings

    def test_standard_changes_nothing(self) -> None:
        """
        The default has to be exactly what `config.py` already says, or adding this
        option silently re-tunes every page that was written before it existed.
        """
        assert d.words_per_heading("standard", 350) == 350
        assert d.max_headings("standard", 6) == 6
        assert d.profile("standard").guidance == ""

    def test_the_spread_is_wide_enough_to_notice(self) -> None:
        """
        Roughly a third and roughly double. A control that moves a 1,400-word page to
        1,200 is a control nobody can tell they used.
        """
        concise = d.words_per_heading("concise", 350) * d.max_headings("concise", 6)
        detailed = d.words_per_heading("detailed", 350) * d.max_headings("detailed", 6)

        assert detailed >= concise * 3

    def test_the_two_long_levels_carry_an_instruction(self) -> None:
        """
        The number alone does not do it. A budget is something a model overshoots;
        the sentence is what changes the shape of the prose.
        """
        assert d.profile("concise").guidance
        assert d.profile("detailed").guidance

    @pytest.mark.parametrize("configured,floor", [(10, 80), (0, 80), (-5, 80)])
    def test_words_never_collapse(self, configured: int, floor: int) -> None:
        assert d.words_per_heading("concise", configured) >= floor

    def test_headings_never_collapse(self) -> None:
        """A page with one heading is not a page, it is a titled paragraph."""
        assert d.max_headings("concise", 2) >= 2


class TestAnUnknownDepthIsNotAFailure:
    """
    A job row written by an older version has no `depth`, and one written by a newer
    one may have a level this code does not know. Either way the answer is a normal
    page — not a composition that dies ten minutes in, after the repository has been
    loaded and the strategy paid for.
    """

    @pytest.mark.parametrize("value", [None, "", "  ", "enormous", "CONCISE ", 7])
    def test_it_falls_back_to_standard(self, value) -> None:
        got = d.profile(value)
        # `CONCISE ` is the one that should *not* fall back — case and whitespace are
        # a caller being untidy, not a caller meaning something else.
        expected = d.Depth.CONCISE if str(value).strip().lower() == "concise" else d.DEFAULT
        assert got.depth == expected


class TestTheThreeCopiesAgree:
    def test_the_schema_accepts_exactly_the_defined_levels(self) -> None:
        """
        `ComposeRequest.depth` is a `Literal`, not the enum: the schema is base and
        the base may not import an app — that is what `test_module_isolation.py`
        enforces. The duplication is deliberate, so it is checked.
        """
        annotation = ComposeRequest.model_fields["depth"].annotation
        assert set(getattr(annotation, "__args__", ())) == set(d.VALUES)

    def test_the_schema_defaults_to_standard(self) -> None:
        assert ComposeRequest().depth == d.DEFAULT.value

    def test_the_studio_offers_the_same_levels(self) -> None:
        """
        Read out of the source rather than mirrored in a fixture, so this fails when
        somebody adds a level on one side only. Reading with an explicit encoding
        because the default on Windows is cp1252 and the file is not.
        """
        source = (UI / "components" / "docs" / "WriteOptions.tsx").read_text(encoding="utf-8")
        offered = set(re.findall(r"id:\s*'([a-z]+)'", source))

        assert offered == set(d.VALUES), (
            "WriteOptions.tsx and depth.py disagree about what levels exist"
        )

    def test_the_studio_type_lists_the_same_levels(self) -> None:
        types = (UI / "lib" / "types.ts").read_text(encoding="utf-8")
        union = re.search(r"export type Depth =([^\n]+)", types)

        assert union, "the Depth union has moved or gone"
        assert set(re.findall(r"'([a-z]+)'", union.group(1))) == set(d.VALUES)

    def test_the_studio_labels_every_level_it_offers(self) -> None:
        """A level with no sentence next to it is a level nobody can choose between."""
        source = (UI / "components" / "docs" / "WriteOptions.tsx").read_text(encoding="utf-8")

        # A quote after the colon: `blurb: string` in the type annotation is not one.
        assert len(re.findall(r"blurb:\s*'", source)) == len(d.VALUES)
