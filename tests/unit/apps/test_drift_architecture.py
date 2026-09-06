"""
Two architecture maps, compared.

Two readings and a map per reading have both existed for a while and nothing had put
them side by side. This is the difference between "these modules changed size" and
"the thing that talked to the database no longer does".

The rule the tests exist to hold: **silent unless both readings have a map.** A
knowledge base written before `architecture_json` existed, or one whose call produced
nothing usable, would otherwise make every service look newly added and every edge
newly cut, which is a confident description of nothing.
"""

from __future__ import annotations

import pytest

from codelith.apps.drift.service import DriftReport, DriftService


class Reading:
    """A `KnowledgeBase` reduced to the one column the comparison reads."""

    def __init__(self, architecture_json: object):
        self.architecture_json = architecture_json


def diff(before: object, after: object) -> DriftReport:
    report = DriftReport(project_id=1, from_commit="a", to_commit="b")
    DriftService._architecture(report, Reading(before), Reading(after))
    return report


def app(*names: str, relations: list[dict] | None = None, types: dict | None = None) -> dict:
    types = types or {}
    return {
        "services": [{"name": n, "type": types.get(n, "service")} for n in names],
        "relations": relations or [],
    }


class TestServices:
    def test_one_appeared(self):
        out = diff(app("api"), app("api", "worker"))
        assert [(s.name, s.change) for s in out.services] == [("worker", "added")]

    def test_one_went(self):
        out = diff(app("api", "cache"), app("api"))
        assert [(s.name, s.change) for s in out.services] == [("cache", "removed")]

    def test_one_became_something_else(self):
        """
        An `api` that is now a `worker` is a rewrite, not a rename. Without this the
        diagram looks unchanged and the diff says nothing happened.
        """
        out = diff(app("x", types={"x": "api"}), app("x", types={"x": "worker"}))
        assert [(s.name, s.change) for s in out.services] == [("x", "retyped")]
        assert out.services[0].type_before == "api"
        assert out.services[0].type_after == "worker"

    def test_an_unchanged_service_is_not_reported(self):
        assert diff(app("api"), app("api")).services == []

    def test_the_order_is_stable(self):
        out = diff(app("a"), app("a", "z", "m"))
        assert [s.name for s in out.services] == ["m", "z"]


class TestRelations:
    def test_a_connection_appeared(self):
        out = diff(
            app("a", "b"),
            app("a", "b", relations=[{"from": "a", "to": "b", "kind": "calls"}]),
        )
        assert [(r.source, r.target, r.change) for r in out.relations] == [("a", "b", "added")]

    def test_a_connection_broke(self):
        out = diff(
            app("a", "b", relations=[{"from": "a", "to": "b", "kind": "calls"}]),
            app("a", "b"),
        )
        assert out.relations[0].change == "removed"
        assert out.relations[0].kind_before == "calls"

    def test_a_verb_that_changed_is_one_edge_reworded(self):
        """
        Keyed on the pair rather than on the whole triple. Otherwise `a calls b`
        becoming `a configures b` reads as one edge cut and another opened, which
        makes an ordinary rename look like a rewiring.
        """
        out = diff(
            app("a", "b", relations=[{"from": "a", "to": "b", "kind": "calls"}]),
            app("a", "b", relations=[{"from": "a", "to": "b", "kind": "configures"}]),
        )
        assert len(out.relations) == 1
        assert out.relations[0].change == "reworded"
        assert (out.relations[0].kind_before, out.relations[0].kind) == ("calls", "configures")

    def test_an_unchanged_edge_is_not_reported(self):
        both = app("a", "b", relations=[{"from": "a", "to": "b", "kind": "calls"}])
        assert diff(both, both).relations == []


class TestTheGuard:
    """The part that keeps the feature honest on real history."""

    @pytest.mark.parametrize("missing", [None, {}, {"services": []}, "junk", 42])
    def test_nothing_is_claimed_when_a_reading_has_no_map(self, missing):
        """
        Every knowledge base written before the architecture agent landed. Diffing a
        map against nothing would list every service as newly added.
        """
        out = diff(missing, app("api", "worker"))
        assert out.architecture_comparable is False
        assert out.services == [] and out.relations == []

    def test_nor_when_the_newer_one_has_none(self):
        out = diff(app("api"), None)
        assert out.architecture_comparable is False and out.services == []

    def test_comparable_only_when_both_sides_have_one(self):
        assert diff(app("a"), app("b")).architecture_comparable is True

    def test_a_malformed_map_does_not_raise(self):
        """`architecture_json` is model output. `coerce` is what makes this safe, and
        this is the assertion that drift did not route around it."""
        out = diff({"services": "not a list", "relations": 7}, app("a"))
        assert out.architecture_comparable is False


class TestTheSummary:
    def test_it_says_what_the_change_meant(self):
        report = diff(
            app("api", "cache", relations=[{"from": "api", "to": "cache", "kind": "reads"}]),
            app("api", "worker"),
        )
        summary = report.summary()
        assert "1 service(s) appeared" in summary
        assert "1 service(s) went" in summary
        assert "1 connection(s) broke" in summary

    def test_an_architecture_only_change_is_not_an_empty_report(self):
        """
        `is_empty` used to ask only about modules and entities. A release that moved
        no module but rewired two services would have reported "nothing structural
        changed" while the diagram was different.
        """
        report = diff(app("a"), app("a", "b"))
        assert report.is_empty is False
        assert "Nothing structural changed" not in report.summary()
