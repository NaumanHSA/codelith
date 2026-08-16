"""
What a codebase unlocks, and the drift this replaced.

Four call sites each decided independently whether a knowledge base could serve a
request. Three wrote out `(READY, STALE, DEGRADED)` by hand; the fourth used
`KBStatus.is_usable`, which excludes `STALE` — so the same project could offer a
feature on one screen and refuse it on another, and nothing failed loudly enough to
notice. `can_serve_features` is now the single definition and this is what pins it.
"""

from __future__ import annotations

import pytest

from codelith.apps import APPS, APPS_BY_ID, AppState, available_ids, state_for
from codelith.knowledge.constants import KBStatus


class TestTheOneDefinition:
    @pytest.mark.parametrize("status", [KBStatus.READY, KBStatus.DEGRADED, KBStatus.STALE])
    def test_a_usable_build_serves_features(self, status: KBStatus) -> None:
        assert status.can_serve_features is True

    def test_stale_still_serves(self) -> None:
        """The load-bearing one. A stale build has been superseded — the code moved
        on — but what it holds is a true account of an older commit. Refusing it would
        mean the studio goes dark the moment somebody pushes."""
        assert KBStatus.STALE.can_serve_features is True
        assert KBStatus.STALE.is_usable is False, (
            "the two are deliberately different; if this ever agrees, one of them is "
            "redundant and the wrong one will get deleted"
        )

    @pytest.mark.parametrize("status", [KBStatus.PENDING, KBStatus.RUNNING, KBStatus.FAILED])
    def test_an_unfinished_or_failed_build_does_not(self, status: KBStatus) -> None:
        assert status.can_serve_features is False


class TestAppState:
    def test_an_analysed_project_unlocks_everything_built(self) -> None:
        assert set(available_ids("ready")) == {f.id for f in APPS if f.built}

    def test_a_project_never_analysed_unlocks_nothing(self) -> None:
        assert available_ids(None) == []

    def test_never_analysed_reads_as_a_next_step_not_an_error(self) -> None:
        """A project nobody has analysed is not broken. The copy has to say what to
        do, because this is the state every new project starts in."""
        state, reason = state_for(APPS[0], None)

        assert state is AppState.LOCKED
        assert "Analyse" in reason

    def test_a_running_analysis_says_so(self) -> None:
        state, reason = state_for(APPS[0], "running")

        assert state is AppState.LOCKED
        assert "running" in reason.lower()

    def test_a_failed_analysis_says_run_it_again(self) -> None:
        state, reason = state_for(APPS[0], "failed")

        assert state is AppState.LOCKED
        assert "again" in reason.lower()

    def test_an_available_feature_needs_no_explanation(self) -> None:
        assert state_for(APPS[0], "ready") == (AppState.AVAILABLE, "")


class TestTheRegistryItself:
    def test_every_feature_is_described_for_a_reader(self) -> None:
        for f in APPS:
            assert f.label and f.blurb and f.route
            assert f.needs, f"{f.id}: a feature is defined by what it needs from the KB"

    def test_ids_are_unique(self) -> None:
        assert len(APPS_BY_ID) == len(APPS)

    def test_every_route_carries_the_project(self) -> None:
        """The registry produces the studio's links. A route that forgets the project
        sends the reader to whichever one happens to be selected."""
        for f in APPS:
            assert "{id}" in f.route, f"{f.id}: route must be project-scoped"

    def test_an_unbuilt_feature_is_planned_regardless_of_the_kb(self) -> None:
        """Planned features are a promise made inside the product. A ready knowledge
        base must not make one look clickable."""
        from dataclasses import replace

        planned = replace(APPS[0], built=False)

        assert state_for(planned, "ready")[0] is AppState.PLANNED
        assert state_for(planned, None)[0] is AppState.PLANNED


class TestAPlannedApp:
    """
    An app registered before it is built. QA was one for a day — the card is how the
    shape of the product becomes legible without marketing copy — and the property
    outlives any particular app, so it is tested with a synthetic one rather than
    whichever app happens to be unbuilt this week.
    """

    @staticmethod
    def _planned():
        from dataclasses import replace

        return replace(APPS[0], id="planned-thing", built=False)

    def test_a_planned_app_is_never_available(self) -> None:
        """However ready the knowledge base is. A card that looks clickable and is
        not is worse than one that says "soon"."""
        planned = self._planned()

        for status in ("ready", "stale", "degraded", "running", "failed", None):
            assert state_for(planned, status)[0] is AppState.PLANNED, status

    def test_a_planned_app_is_not_offered_as_available(self) -> None:
        planned = self._planned()

        assert state_for(planned, "ready")[0] is not AppState.AVAILABLE

    def test_every_registered_app_declares_what_it_would_read(self) -> None:
        """An app with no `needs` is a name on a card. Deciding what it reads from the
        knowledge base is the design work — it is what says whether the base already
        holds enough, or whether analysis has to change for it."""
        for app in APPS:
            assert app.needs, app.id

    def test_quality_is_not_registered_while_it_is_parked(self) -> None:
        """Quality lives on `feat/qa` until documentation and Ask settle. A registry
        entry for something `main` cannot serve is a promise the studio breaks."""
        assert "qa" not in APPS_BY_ID
