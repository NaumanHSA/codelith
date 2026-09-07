"""
Grouping modules by what this codebase is, not by what every codebase has.

`ModuleRole` is twelve fixed words. It is stable, which is what the apps need, and it
is the same twelve words in every repository, which is why the knowledge graph read as
canned: `SERVICE` says a module is not a test, not that it is the face tracking engine.

The architecture pass already names components per codebase and lists their modules.
Nothing here computes anything new or calls a model; it reads that and answers which
component a module belongs to.
"""

import pytest

from codelith.knowledge.services import assign, components

WATCHTOWER = {
    "services": [
        {"name": "Controller API", "type": "api",
         "modules": ["controller.app.routers", "controller.app"]},
        {"name": "Worker Face Tracking Engine", "type": "processing",
         "modules": ["worker.app.engine"]},
        {"name": "Controller Persistence", "type": "data_access",
         "modules": ["controller.app.db"]},
    ]
}


class TestReadingWhatAnalysisWrote:
    def test_components_come_back_named(self):
        got = components(WATCHTOWER)
        assert [c.name for c in got] == [
            "Controller API", "Worker Face Tracking Engine", "Controller Persistence"
        ]
        assert got[0].kind == "api"

    @pytest.mark.parametrize("junk", [None, "a string", 42, [], {"services": "not a list"}])
    def test_anything_unusable_is_no_components(self, junk):
        """`architecture_json` is a JSON column and holds whatever was written to it,
        including a scalar."""
        assert components(junk) == []

    def test_a_repeated_name_is_kept_once(self):
        doubled = {"services": [{"name": "API"}, {"name": "api"}]}
        assert len(components(doubled)) == 1


class TestAssignment:
    def test_a_listed_module_takes_its_component(self):
        got = assign(WATCHTOWER, ["worker.app.engine"])
        assert got["worker.app.engine"] == "Worker Face Tracking Engine"

    def test_a_module_the_pass_never_saw_is_left_alone(self):
        """Unassigned is the honest answer, and the graph falls back to the role."""
        assert assign(WATCHTOWER, ["worker.app.something_else"]) == {}

    def test_a_parent_inherits_from_agreeing_children(self):
        """
        The architecture pass names leaves and skips the packages holding them, so a
        direct reading covered barely half a real repository.
        """
        got = assign(
            {"services": [{"name": "Engine", "modules": ["w.engine.track", "w.engine.detect"]}]},
            ["w.engine", "w.engine.track", "w.engine.detect"],
        )
        assert got["w.engine"] == "Engine"

    def test_a_mixed_parent_inherits_nothing(self):
        """`codelith.apps` holds documentation, ask and drift. It is none of them."""
        got = assign(
            {"services": [
                {"name": "Docs", "modules": ["app.apps.documentation"]},
                {"name": "Ask", "modules": ["app.apps.ask"]},
            ]},
            ["app.apps", "app.apps.documentation", "app.apps.ask"],
        )
        assert "app.apps" not in got

    def test_a_leaf_inherits_from_its_nearest_ancestor(self):
        got = assign(
            {"services": [{"name": "Agent Runtime", "modules": ["n.agents"]}]},
            ["n.agents", "n.agents.conversation"],
        )
        assert got["n.agents.conversation"] == "Agent Runtime"

    def test_the_nearest_ancestor_wins_over_a_broader_one(self):
        got = assign(
            {"services": [
                {"name": "Broad", "modules": ["n.a"]},
                {"name": "Specific", "modules": ["n.a.b"]},
            ]},
            ["n.a", "n.a.b", "n.a.b.c"],
        )
        assert got["n.a.b.c"] == "Specific"

    def test_the_root_package_is_never_inherited_from(self):
        """
        The trade this exists to refuse. Allowing it, `codelith` was placed in
        "Codelith API" and every module without an answer of its own inherited that,
        including `codelith.mcp`, which is a second transport over the knowledge base
        and not the API. Coverage rose and the labels stopped being true.
        """
        got = assign(
            {"services": [{"name": "The API", "modules": ["pkg"]}]},
            ["pkg", "pkg.mcp"],
        )
        assert got["pkg"] == "The API"
        assert "pkg.mcp" not in got

    def test_a_module_is_claimed_by_one_component_only(self):
        got = assign(
            {"services": [
                {"name": "First", "modules": ["shared"]},
                {"name": "Second", "modules": ["shared"]},
            ]},
            ["shared"],
        )
        assert got["shared"] == "First"

    def test_no_architecture_assigns_nothing(self):
        """A knowledge base written before the architecture pass existed still works;
        every module falls back to its role."""
        assert assign(None, ["a", "b"]) == {}


class TestTheAssembledResult:
    def test_modules_carry_their_component(self):
        from codelith.services.module_service import assemble

        class Row:
            path, name, kind, role = "worker/app/engine", "worker.app.engine", "package", "service"
            language, file_count, loc, is_test = "python", 3, 400, False
            summary, files_json, symbols_json = "Tracks faces.", [], []

        out = assemble([Row()], "abc123", WATCHTOWER)
        assert out.modules[0].service == "Worker Face Tracking Engine"
        assert out.modules[0].role == "service"

    def test_it_is_empty_rather_than_absent_without_architecture(self):
        from codelith.services.module_service import assemble

        class Row:
            path, name, kind, role = "a/b", "a.b", "package", "utility"
            language, file_count, loc, is_test = "python", 1, 10, False
            summary, files_json, symbols_json = "", [], []

        out = assemble([Row()], "abc123", None)
        assert out.modules[0].service == ""
