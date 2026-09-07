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


def svc(name: str, modules: list[str], type_: str = "service") -> dict:
    return {"name": name, "type": type_, "modules": modules}


def mapped(*services: dict, relations: list[dict] | None = None) -> dict:
    return {"services": list(services), "relations": relations or []}


class TestServicesAreMatchedByWhatIsInThem:
    """
    Service names are the model's words, and two readings of an unchanged repository
    do not agree on them: "HTTP API" one run, "Codelith API" the next. Keyed on name,
    a diff of two readings three commits apart reported nine services added and eight
    removed — a headline that was almost entirely rename noise.

    Module names come from the code, so they are the same in both readings whatever
    the model called the thing containing them. That is the identity being matched on.
    """

    def test_a_renamed_service_is_a_rename_not_a_replacement(self):
        out = diff(
            mapped(svc("HTTP API", ["app.api", "app.routes"], "api")),
            mapped(svc("Codelith API", ["app.api", "app.routes"], "api")),
        )
        assert [(s.change, s.name, s.name_before) for s in out.services] == [
            ("renamed", "Codelith API", "HTTP API")
        ]

    def test_a_rename_survives_the_service_gaining_modules(self):
        """The commit that renames a thing is often the commit that grew it."""
        out = diff(
            mapped(svc("Worker", ["app.jobs", "app.queue"])),
            mapped(svc("Async Workflow Worker", ["app.jobs", "app.queue", "app.retry"])),
        )
        assert [s.change for s in out.services] == ["renamed"]

    def test_two_different_services_are_not_merged(self):
        """Sharing nothing means they are not the same thing under a new name."""
        out = diff(
            mapped(svc("Cache", ["app.cache"])),
            mapped(svc("Mailer", ["app.mail"])),
        )
        assert sorted((s.change, s.name) for s in out.services) == [
            ("added", "Mailer"),
            ("removed", "Cache"),
        ]

    def test_a_service_with_no_modules_cannot_be_matched(self):
        """No evidence of identity, so the honest answer is added and removed."""
        out = diff(mapped(svc("A", [])), mapped(svc("B", [])))
        assert sorted(s.change for s in out.services) == ["added", "removed"]

    def test_a_genuinely_new_service_still_reads_as_added(self):
        out = diff(
            mapped(svc("API", ["app.api"])),
            mapped(svc("API", ["app.api"]), svc("Worker", ["app.jobs"])),
        )
        assert [(s.change, s.name) for s in out.services] == [("added", "Worker")]

    def test_an_exact_name_match_wins_over_a_module_match(self):
        """When the model agrees with itself, that is the answer."""
        out = diff(
            mapped(svc("API", ["app.api"]), svc("Old", ["app.jobs"])),
            mapped(svc("API", ["app.api", "app.jobs"]), svc("New", ["app.jobs"])),
        )
        changes = {(s.change, s.name) for s in out.services}
        assert ("renamed", "New") in changes
        assert not any(s.name == "API" for s in out.services)

    def test_each_service_is_used_once(self):
        """Two candidates cannot both claim the same partner."""
        out = diff(
            mapped(svc("One", ["a", "b"])),
            mapped(svc("Two", ["a", "b"]), svc("Three", ["a", "b"])),
        )
        assert sorted(s.change for s in out.services) == ["added", "renamed"]


class TestRelationsFollowTheRename:
    def test_an_edge_between_renamed_services_is_not_reported_as_cut(self):
        """
        The bug this closes: renaming both ends of an edge reported the connection
        broken and a new one opened, when nothing about the wiring changed.
        """
        out = diff(
            mapped(
                svc("HTTP API", ["app.api"], "api"),
                svc("Store", ["app.db"], "data_access"),
                relations=[{"source": "HTTP API", "target": "Store", "kind": "reads"}],
            ),
            mapped(
                svc("Codelith API", ["app.api"], "api"),
                svc("Persistence", ["app.db"], "data_access"),
                relations=[{"source": "Codelith API", "target": "Persistence", "kind": "reads"}],
            ),
        )
        assert out.relations == []
        assert sorted(s.change for s in out.services) == ["renamed", "renamed"]

    def test_a_real_cut_is_still_reported_across_a_rename(self):
        out = diff(
            mapped(
                svc("HTTP API", ["app.api"], "api"),
                svc("Store", ["app.db"], "data_access"),
                relations=[{"source": "HTTP API", "target": "Store", "kind": "reads"}],
            ),
            mapped(
                svc("Codelith API", ["app.api"], "api"),
                svc("Store", ["app.db"], "data_access"),
                relations=[],
            ),
        )
        assert [(r.source, r.target, r.change) for r in out.relations] == [
            ("Codelith API", "Store", "removed")
        ]


class TestTheSentenceNamesARenameAsARename:
    def test_renames_are_not_counted_as_appearances(self):
        out = diff(
            mapped(svc("HTTP API", ["app.api"], "api")),
            mapped(svc("Codelith API", ["app.api"], "api")),
        )
        sentence = out.summary()
        assert "1 renamed" in sentence
        assert "appeared" not in sentence
        assert "went" not in sentence
