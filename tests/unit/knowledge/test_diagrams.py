"""
Diagrams built from the graph, not written by a model.

Diagrams were switched off because generated Mermaid was unreliable, and the cause
is structural: Mermaid is roughly eight grammars under one name, so a model blends
them — a flowchart arrow inside a `classDiagram`, `end` as a node id, unescaped
parentheses in a label. Switching to D2 helps, but a friendlier syntax to get wrong
is not a fix.

The fix is that no model writes syntax. A builder takes nodes and edges and prints
valid D2, so three properties hold by construction and are asserted here:

* **Nothing ungrounded.** A node cannot appear unless a caller added it, and an edge
  to a node nobody added is dropped rather than drawn — D2 would otherwise create
  the missing node implicitly, which is exactly the invented box this replaces.
* **Nothing malformed.** There is no free-text path into the output.
* **Nothing pointless.** A diagram with too little in it returns `None`, because a
  picture of two boxes occupies the space an explanation should have had.
"""

from __future__ import annotations

from app.knowledge.constants import EntityKind
from app.knowledge.diagrams import blast_radius, entity_map, module_map, system_context
from app.tools.d2 import D2Diagram, ident

FILES = [
    {"path": "app/api/v1/jobs.py", "module_key": "app/api/v1"},
    {"path": "app/services/job_service.py", "module_key": "app/services"},
    {"path": "app/services/site_service.py", "module_key": "app/services"},
    {"path": "app/db/session.py", "module_key": "app/db"},
    {"path": "app/db/repo.py", "module_key": "app/db"},
]
IMPORTS = [
    {"src": "app/api/v1/jobs.py", "dst": "app/services/job_service.py"},
    {"src": "app/services/job_service.py", "dst": "app/db/session.py"},
    {"src": "app/services/site_service.py", "dst": "app/db/session.py"},
    {"src": "app/services/site_service.py", "dst": "app/db/repo.py"},
]
ROLES = {"app/api/v1": "api", "app/services": "service", "app/db": "data_access"}

ENTITIES = [
    {"kind": str(EntityKind.DATASTORE), "name": "Redis", "data_json": {"engine": "key_value"}},
    {"kind": str(EntityKind.DATASTORE), "name": "Neo4j", "data_json": {"engine": "graph"}},
    {"kind": str(EntityKind.EXTERNAL_API), "name": "api.openai.com", "data_json": {}},
    {"kind": str(EntityKind.ENTRYPOINT), "name": "app/main.py", "data_json": {}},
    {"kind": str(EntityKind.ROUTE), "name": "GET /jobs", "data_json": {}},
    {"kind": str(EntityKind.ROUTE), "name": "POST /jobs", "data_json": {}},
]


class TestIdentifiersAreSafe:
    def test_a_path_does_not_become_nested_containers(self) -> None:
        """A dot is nesting in D2, so `app/db/session.py` keyed raw silently becomes
        four nested containers — and the diagram quietly describes a structure that
        does not exist."""
        assert "." not in ident("app/db/session.py")
        assert "/" not in ident("app/db/session.py")

    def test_identifiers_never_come_back_empty(self) -> None:
        for text in ("", "...", "///", "---", "  "):
            assert ident(text)

    def test_a_label_with_quotes_survives(self) -> None:
        diagram = D2Diagram()
        diagram.node('a "quoted" name')

        rendered = diagram.render()

        assert '\\"quoted\\"' in rendered

    def test_a_label_with_a_newline_stays_on_one_line(self) -> None:
        diagram = D2Diagram()
        diagram.node("first\nsecond")

        for line in diagram.render().splitlines():
            assert line.count("label:") <= 1


class TestNothingUngroundedIsDrawn:
    def test_an_edge_to_a_node_that_was_never_added_is_dropped(self) -> None:
        """D2 creates missing nodes implicitly. An implicitly-created node is an
        invented box, which is the whole failure this approach removes."""
        diagram = D2Diagram()
        real = diagram.node("real")

        diagram.edge(real, ident("never_added"))

        assert diagram.edges == []
        assert "never_added" not in diagram.render()

    def test_a_self_edge_is_dropped(self) -> None:
        diagram = D2Diagram()
        node = diagram.node("thing")

        diagram.edge(node, node)

        assert diagram.edges == []

    def test_adding_the_same_key_twice_is_one_node(self) -> None:
        diagram = D2Diagram()
        diagram.node("Redis", key="store::Redis")
        diagram.node("Redis", key="store::Redis")

        assert len(diagram.nodes) == 1

    def test_the_same_edge_twice_is_drawn_once(self) -> None:
        diagram = D2Diagram()
        a, b = diagram.node("a"), diagram.node("b")

        diagram.edge(a, b)
        diagram.edge(a, b)

        assert len(diagram.edges) == 1


class TestModuleMap:
    def test_file_imports_are_aggregated_to_modules(self) -> None:
        """A hundred file imports become a handful of module dependencies, which is
        the level a reader can hold in their head."""
        source = module_map(FILES, IMPORTS, ROLES)

        assert source is not None
        assert "app/api/v1" in source
        assert "app/services" in source
        # Two files importing the same module is one edge between modules.
        assert source.count("app_services -> app_db") <= 1

    def test_modules_are_grouped_by_role(self) -> None:
        source = module_map(FILES, IMPORTS, ROLES)

        assert 'label: "api"' in source
        assert 'label: "data access"' in source

    def test_a_trivial_repository_gets_no_diagram(self) -> None:
        """Two modules and one edge is a restatement of the file list."""
        assert module_map(FILES[:2], IMPORTS[:1], ROLES) is None

    def test_a_repository_with_no_internal_imports_gets_no_diagram(self) -> None:
        assert module_map(FILES, [], ROLES) is None

    def test_edges_reference_real_nodes(self) -> None:
        """Every arrow endpoint must be a node the diagram declared."""
        source = module_map(FILES, IMPORTS, ROLES)
        declared = {
            line.split(":")[0].strip()
            for line in source.splitlines()
            if line.strip().endswith("{") and ":" in line
        }

        for line in source.splitlines():
            if "->" in line:
                left, right = line.split("->", 1)
                for endpoint in (left.strip(), right.split(":")[0].strip()):
                    leaf = endpoint.split(".")[-1]
                    assert leaf in declared, f"{leaf} is not declared"


class TestSystemContext:
    def test_datastores_and_apis_are_drawn(self) -> None:
        source = system_context(ENTITIES, "document-anything")

        assert source is not None
        assert "Redis" in source and "Neo4j" in source
        assert "api.openai.com" in source

    def test_a_datastore_looks_like_storage(self) -> None:
        source = system_context(ENTITIES, "proj")

        assert "shape: cylinder" in source

    def test_entrypoint_labels_are_names_not_data(self) -> None:
        """The first version iterated `(name, data)` pairs as if they were names, and
        every entrypoint was labelled with a stringified tuple."""
        source = system_context(ENTITIES, "proj")

        assert "app/main.py" in source
        assert "{'language'" not in source
        assert "(" not in source.split("in_")[-1].split("\n")[0]

    def test_a_project_with_nothing_external_gets_no_diagram(self) -> None:
        assert system_context([ENTITIES[3]], "proj") is None


class TestBlastRadius:
    DEPENDENTS = [
        {"file": "app/services/a.py", "distance": 1},
        {"file": "app/services/b.py", "distance": 1},
        {"file": "app/api/c.py", "distance": 2},
    ]

    def test_files_are_grouped_by_distance(self) -> None:
        source = blast_radius("app/config.py", self.DEPENDENTS)

        assert source is not None
        assert "1 hop away" in source
        assert "2 hops away" in source

    def test_the_count_is_shown_rather_than_every_file(self) -> None:
        source = blast_radius("app/config.py", self.DEPENDENTS)

        assert "2 file(s)" in source

    def test_nothing_downstream_means_no_diagram(self) -> None:
        assert blast_radius("app/leaf.py", []) is None


class TestEntityMap:
    def test_routes_are_drawn(self) -> None:
        source = entity_map(ENTITIES, EntityKind.ROUTE, "HTTP surface")

        assert source is not None
        assert "GET /jobs" in source and "POST /jobs" in source

    def test_a_single_fact_is_not_a_diagram(self) -> None:
        assert entity_map(ENTITIES, EntityKind.EXTERNAL_API, "Integrations") is None


class TestRenderedOutputIsWellFormed:
    """Structural checks that hold without D2 installed. When the binary is present,
    `d2_render.validate` runs the real compiler."""

    def _sources(self) -> list[str]:
        return [
            s for s in (
                module_map(FILES, IMPORTS, ROLES),
                system_context(ENTITIES, "proj"),
                blast_radius("app/config.py", TestBlastRadius.DEPENDENTS),
                entity_map(ENTITIES, EntityKind.ROUTE, "HTTP surface"),
            ) if s
        ]

    def test_braces_balance(self) -> None:
        for source in self._sources():
            assert source.count("{") == source.count("}"), source[:200]

    def test_every_diagram_declares_a_direction(self) -> None:
        for source in self._sources():
            assert "direction:" in source

    def test_no_unquoted_label_text(self) -> None:
        """An unquoted label containing a colon or a brace is a parse error."""
        for source in self._sources():
            for line in source.splitlines():
                if line.strip().startswith("label:"):
                    assert line.split("label:", 1)[1].strip().startswith('"')

    def test_it_is_accepted_by_d2_when_d2_is_available(self) -> None:
        from app.tools.d2_render import d2_cli, validate

        if not d2_cli():
            import pytest

            pytest.skip("d2 binary not installed")
        for source in self._sources():
            ok, message = validate(source)
            assert ok, message
