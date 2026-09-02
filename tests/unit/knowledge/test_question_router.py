"""
Routing a question to the right store.

`SectionContextBuilder` answers "evidence for this known section". A question is a
different shape — nobody has decided what it is about yet — so something must choose
between code, prose, entities, narratives and the graph before any of them is
queried. That choice is what these cases are about.

The router is deterministic on purpose, which is what makes it testable at all: an
LLM router would be one more thing to blame when retrieval is bad, and the point of
this phase is measuring whether K1–K3 produced a substrate worth building on.

Two failure modes, and the second is the expensive one:

* **Under-routing** — a traversal question ("what calls X") answered by vector
  search, which structurally cannot answer it. No embedding of a function body
  encodes its callers.
* **Over-routing** — chasing a symbol the asker never named. Measured: "what calls
  the tool registry" matched the symbol `tool`, because `tool` is both an ordinary
  English word and a real identifier, so the graph was traversed for something
  nobody asked about and returned nothing.
"""

from __future__ import annotations

from codelith.knowledge.questions import Evidence, EvidenceBundle, QuestionPlan, plan_question

SYMBOLS = {
    "ToolPool", "get", "register_tool_factory", "create_async_engine",
    "tool", "run", "Guardrails", "config",
}


class TestSemanticSearchAlwaysRuns:
    """Routing decides what to *add*, never what to remove. A misrouted question
    should return more than it needs, never less."""

    def test_a_plain_question_still_searches(self) -> None:
        plan = plan_question("what does this project do")

        assert plan.intents == ["semantic"]

    def test_semantic_survives_every_other_intent(self) -> None:
        plan = plan_question("how does `ToolPool.get` work and what calls it", SYMBOLS)

        assert "semantic" in plan.intents


class TestTraversalQuestions:
    """The questions vector search cannot answer at all."""

    def test_what_calls_routes_to_the_graph(self) -> None:
        assert "graph" in plan_question("what calls the scheduler").intents

    def test_impact_questions_route_to_the_graph(self) -> None:
        for question in (
            "what breaks if I change the config module",
            "what depends on the LLM client",
            "blast radius of the session factory",
            "who imports the tool registry",
        ):
            assert "graph" in plan_question(question).intents, question

    def test_a_file_path_routes_to_the_graph(self) -> None:
        plan = plan_question("what uses app/db/session.py")

        assert plan.paths == ["app/db/session.py"]
        assert "graph" in plan.intents

    def test_prose_about_files_is_not_mistaken_for_a_path(self) -> None:
        plan = plan_question("how does the session handling work")

        assert plan.paths == []


class TestSymbolRecognition:
    """The over-routing failure, found by running the inspector for real."""

    def test_a_common_english_word_is_not_chased_as_a_symbol(self) -> None:
        """`tool` is both an ordinary word and a real identifier in this KB. Matching
        it sent the router traversing for something nobody named."""
        plan = plan_question("what calls the tool registry", SYMBOLS)

        assert plan.symbols == []

    def test_a_backticked_symbol_is_recognised(self) -> None:
        plan = plan_question("what calls `register_tool_factory`", SYMBOLS)

        assert "register_tool_factory" in plan.symbols

    def test_camel_case_is_recognised(self) -> None:
        plan = plan_question("where is ToolPool used", SYMBOLS)

        assert "ToolPool" in plan.symbols

    def test_snake_case_is_recognised(self) -> None:
        plan = plan_question("who calls create_async_engine", SYMBOLS)

        assert "create_async_engine" in plan.symbols

    def test_a_dotted_symbol_also_tries_its_bare_name(self) -> None:
        """The graph stores methods under the bare name too, so `ToolPool.get`
        should reach `get`."""
        plan = plan_question("what calls `ToolPool.get`", SYMBOLS)

        assert "ToolPool" in plan.symbols or "get" in plan.symbols

    def test_an_unknown_identifier_is_not_pursued(self) -> None:
        """A symbol this KB does not define is a typo or a concept. Either way the
        lookup finds nothing, and pretending otherwise wastes a traversal."""
        plan = plan_question("what calls `no_such_function`", SYMBOLS)

        assert plan.symbols == []

    def test_symbols_need_a_known_set_to_match_against(self) -> None:
        plan = plan_question("what calls `register_tool_factory`")

        assert plan.symbols == []


class TestEntityQuestions:
    """The KB already holds these as facts. Answering from them beats retrieving code
    and hoping the answer happens to be visible in it."""

    def test_storage_questions_route_to_datastores(self) -> None:
        for question in ("where is data stored", "what database does it use"):
            assert "datastore" in plan_question(question).entity_kinds, question

    def test_integration_questions_route_to_external_apis(self) -> None:
        plan = plan_question("what external services does it talk to")

        assert "external_api" in plan.entity_kinds
        assert "entities" in plan.intents

    def test_schedule_questions_route_to_scheduled_tasks(self) -> None:
        plan = plan_question("what runs on a schedule")

        assert "scheduled_task" in plan.entity_kinds

    def test_endpoint_questions_route_to_routes(self) -> None:
        plan = plan_question("what endpoints does it expose")

        assert "route" in plan.entity_kinds

    def test_a_phrase_inside_a_longer_word_does_not_match(self) -> None:
        """Measured on the question set: "what imports the LLM client" routed to
        `cli_command`, because "client" contains — and starts with — "cli"."""
        plan = plan_question("what imports the LLM client")

        assert "cli_command" not in plan.entity_kinds

    def test_a_real_cli_question_still_matches(self) -> None:
        assert "cli_command" in plan_question("what cli commands are there").entity_kinds

    def test_an_unrelated_question_asks_for_no_entities(self) -> None:
        plan = plan_question("what does this project do")

        assert plan.entity_kinds == []
        assert "entities" not in plan.intents


class TestNarrativeQuestions:
    def test_how_questions_reach_for_a_narrative(self) -> None:
        for question in (
            "how does a request flow through the system",
            "what happens when a job fails",
            "explain the graph engine",
        ):
            assert "narrative" in plan_question(question).intents, question

    def test_a_lookup_question_does_not(self) -> None:
        plan = plan_question("what endpoints does it expose")

        assert "narrative" not in plan.intents


class TestEvidenceBundle:
    def test_counts_are_reported_per_kind(self) -> None:
        bundle = EvidenceBundle(plan=QuestionPlan(question="q"))
        bundle.items = [
            Evidence(kind="code", title="a", body="x", why="w"),
            Evidence(kind="code", title="b", body="y", why="w"),
            Evidence(kind="graph", title="c", body="z", why="w"),
        ]

        assert bundle.counts == {"code": 2, "graph": 1}

    def test_evidence_carries_the_reason_it_was_retrieved(self) -> None:
        """A retrieval layer that cannot explain a result cannot be debugged, and
        finding where K1-K3 fall short is the entire purpose of this phase."""
        item = Evidence(kind="graph", title="callers of X", body="…", why="named a symbol")

        assert item.why
        assert "[graph]" in item.render()

    def test_an_empty_bundle_says_so(self) -> None:
        bundle = EvidenceBundle(plan=QuestionPlan(question="q"))

        assert bundle.render() == "(no evidence found)"

    def test_the_plan_is_legible(self) -> None:
        plan = plan_question("what calls `ToolPool` in app/db/session.py", SYMBOLS)

        described = plan.describe()
        assert "graph" in described
        assert "app/db/session.py" in described
