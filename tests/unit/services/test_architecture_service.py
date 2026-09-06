"""
Making model output safe to draw.

`architecture_json` is written by a quality-tier call and stored verbatim. Every
assumption a renderer would like to make about it is one that somebody's repository
will break, so the whole of `_coerce` is defensive and the whole of this file is the
shapes it has to survive.

The rule under all of it: a malformed field costs that field, never the page.
"""

from __future__ import annotations

import pytest

from codelith.services.architecture_service import ArchitectureService


@pytest.fixture
def coerce():
    """`_coerce` alone — it touches neither the database nor the session."""
    service = ArchitectureService.__new__(ArchitectureService)
    return lambda raw, sha="abc1234": service._coerce(raw, sha)


REAL = {
    "services": [
        {"name": "src", "type": "service", "description": "Live capture.", "modules": ["src"]},
        {"name": "server", "type": "api", "description": "Serves keys.", "modules": ["server"]},
    ],
    "relations": [{"from": "src", "to": "server", "kind": "calls"}],
    "layers": [{"name": "Core Logic", "modules": ["src", "src.session"]}],
    "patterns": ["Web Worker", "Hybrid Encryption"],
    "entry_points": ["server/main.py"],
    "tech_stack": {
        "language": "javascript, python",
        "frameworks": ["fastapi", "rollup"],
        "databases": [],
        "infra": ["Dockerfile"],
    },
}


class TestTheShapeAnalysisActuallyWrites:
    """The column as it exists on this machine today."""

    def test_it_reads(self, coerce):
        out = coerce(REAL)
        assert out.available
        assert [s.name for s in out.services] == ["src", "server"]
        assert out.services[0].type == "service"
        assert out.relations[0].source == "src" and out.relations[0].kind == "calls"
        assert out.layers[0].name == "Core Logic"
        assert out.patterns == ["Web Worker", "Hybrid Encryption"]
        assert out.tech_stack.frameworks == ["fastapi", "rollup"]
        assert out.commit_sha == "abc1234"


class TestItSurvivesWhatAModelMightWrite:
    def test_nothing_at_all(self, coerce):
        out = coerce({})
        assert out.available is False and out.services == []

    def test_services_missing(self, coerce):
        """No services means no map. Everything else can be empty and still draw."""
        assert coerce({"patterns": ["x"], "relations": [{"from": "a", "to": "b"}]}).available is False

    @pytest.mark.parametrize("junk", [None, "a string", 42, [], {"services": None}])
    def test_junk_where_a_map_should_be(self, coerce, junk):
        raw = junk if isinstance(junk, dict) else {"services": junk}
        assert coerce(raw).available is False

    def test_a_service_that_is_just_a_name(self, coerce):
        out = coerce({"services": ["gateway", "worker"]})
        assert [s.name for s in out.services] == ["gateway", "worker"]

    def test_a_service_with_no_name_is_dropped(self, coerce):
        out = coerce({"services": [{"type": "api"}, {"name": "real"}]})
        assert [s.name for s in out.services] == ["real"]

    def test_duplicate_services_collapse(self, coerce):
        """Two nodes with one name is a diagram with a node drawn twice."""
        out = coerce({"services": [{"name": "api"}, {"name": "api"}]})
        assert len(out.services) == 1

    @pytest.mark.parametrize(
        "relation",
        [
            {"source": "a", "target": "b", "kind": "calls"},
            {"src": "a", "dst": "b"},
            {"from": "a", "to": "b"},
        ],
    )
    def test_the_several_names_for_an_edge(self, coerce, relation):
        out = coerce({"services": [{"name": "a"}, {"name": "b"}], "relations": [relation]})
        assert out.relations[0].source == "a" and out.relations[0].target == "b"

    def test_an_edge_to_a_service_that_does_not_exist_is_counted_not_drawn(self, coerce):
        """
        The one thing not silently dropped. An edge to nowhere cannot be drawn, and
        pretending it was never there would hide a defect in the analysis.
        """
        out = coerce(
            {
                "services": [{"name": "a"}],
                "relations": [{"from": "a", "to": "ghost"}, {"from": "a", "to": "a"}],
            }
        )
        assert len(out.relations) == 1
        assert out.dangling_relations == 1

    def test_a_half_written_edge_is_dropped(self, coerce):
        out = coerce({"services": [{"name": "a"}], "relations": [{"from": "a"}, "nonsense"]})
        assert out.relations == [] and out.dangling_relations == 0

    def test_modules_written_as_objects(self, coerce):
        """The writer sometimes gives each module a name and a note."""
        out = coerce({"services": [{"name": "a", "modules": [{"name": "src.x"}, "src.y"]}]})
        assert out.services[0].modules == ["src.x", "src.y"]

    def test_a_stack_that_came_back_as_a_string(self, coerce):
        out = coerce({"services": [{"name": "a"}], "tech_stack": "python"})
        assert out.available and out.tech_stack.language == ""

    def test_a_layer_with_no_name_is_dropped(self, coerce):
        out = coerce({"services": [{"name": "a"}], "layers": [{"modules": ["x"]}, {"name": "UI"}]})
        assert [layer.name for layer in out.layers] == ["UI"]

    def test_prose_is_bounded(self, coerce):
        """A description that runs to a page would break the caption strip."""
        out = coerce({"services": [{"name": "a", "description": "x" * 5000}]})
        assert len(out.services[0].description) <= 400

    def test_newlines_do_not_reach_the_diagram(self, coerce):
        out = coerce({"services": [{"name": "a", "description": "one\n\ntwo"}]})
        assert out.services[0].description == "one two"

    def test_a_very_wide_map_is_bounded(self, coerce):
        out = coerce({"services": [{"name": "a"}], "patterns": [f"p{i}" for i in range(200)]})
        assert len(out.patterns) == 20
