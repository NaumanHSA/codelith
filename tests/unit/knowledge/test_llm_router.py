"""
The model-driven router, and the checks that make it safe to trust.

Phrase tables could not survive a codebase nobody has seen — the code and the
phrasing are both unbounded, and "which modules would I need to touch if I
refactored the executor" matches no hand-written trigger. So routing is a model's
job now.

Which moves the risk rather than removing it. A model asked to name symbols will
name plausible ones that do not exist; asked for entity kinds it will produce kinds
this schema never held. **The model proposes and the knowledge base disposes**:
every field is intersected with what actually exists before anything is queried, so
a hallucination costs one dropped list entry instead of a traversal after something
imaginary.

These cases are almost all about that intersection, plus the two invariants that
must survive any routing decision: semantic search always runs, and a failure falls
back to rules rather than returning nothing.
"""

from __future__ import annotations

import pytest

from app.knowledge.questions import KBVocabulary, LLMQuestionPlanner

VOCAB = KBVocabulary(
    entity_kinds=frozenset({"datastore", "route", "env_var"}),
    narrative_topics=frozenset({"architecture", "error_handling", "data_model"}),
    symbols=frozenset({"SessionFactory", "create_async_engine", "ToolPool"}),
    paths=frozenset({"app/db/session.py", "app/main.py"}),
    modules=("app.db", "app.services"),
)


def _plan(raw: dict, question: str = "a question"):
    return LLMQuestionPlanner(VOCAB)._validate(question, raw)


class TestNothingUnrealSurvives:
    """The whole safety argument. Each of these is a hallucination the model can and
    will produce, costing nothing because it is checked."""

    def test_an_invented_entity_kind_is_dropped(self) -> None:
        plan = _plan({"entity_kinds": ["message_queue", "datastore"]})

        assert plan.entity_kinds == ["datastore"]

    def test_an_invented_narrative_topic_is_dropped(self) -> None:
        """This KB has no `auth` narrative. Querying for one returns nothing and
        looks to the reader like retrieval failed."""
        plan = _plan({"narrative_topics": ["auth", "error_handling"]})

        assert plan.narrative_topics == ["error_handling"]

    def test_a_hallucinated_symbol_is_dropped(self) -> None:
        """A plausible-sounding name is exactly what a model produces when it does
        not know. Traversing for it wastes the query and reports nothing found."""
        plan = _plan({"symbols": ["DatabaseManager", "SessionFactory"]})

        assert plan.symbols == ["SessionFactory"]

    def test_a_path_that_does_not_exist_is_dropped(self) -> None:
        plan = _plan({"paths": ["app/db/connection.py", "app/main.py"]})

        assert plan.paths == ["app/main.py"]

    def test_an_unknown_intent_is_dropped(self) -> None:
        """`sql` is not a store. Acting on it would be a KeyError at best."""
        plan = _plan({"intents": ["semantic", "sql", "graph"]})

        assert set(plan.intents) == {"semantic", "graph"}


class TestInvariantsSurviveAnyRouting:
    def test_semantic_is_added_when_the_model_omits_it(self) -> None:
        """Semantic search is the only store that answers when every other route
        misses. A model that drops it has removed the floor."""
        plan = _plan({"intents": ["graph"]})

        assert "semantic" in plan.intents

    def test_semantic_survives_an_empty_response(self) -> None:
        plan = _plan({})

        assert plan.intents == ["semantic"]

    def test_naming_an_entity_kind_turns_on_the_entity_intent(self) -> None:
        """A model that names kinds but forgets the intent should still get them —
        the fields are the stronger signal."""
        plan = _plan({"intents": ["semantic"], "entity_kinds": ["route"]})

        assert "entities" in plan.intents

    def test_naming_a_topic_turns_on_the_narrative_intent(self) -> None:
        plan = _plan({"intents": ["semantic"], "narrative_topics": ["architecture"]})

        assert "narrative" in plan.intents

    def test_naming_a_symbol_turns_on_the_graph_intent(self) -> None:
        plan = _plan({"intents": ["semantic"], "symbols": ["ToolPool"]})

        assert "graph" in plan.intents


class TestMalformedResponses:
    """A small model returns whatever it likes. None of it should raise."""

    def test_a_string_where_a_list_belongs_is_accepted(self) -> None:
        plan = _plan({"entity_kinds": "datastore", "intents": "semantic"})

        assert plan.entity_kinds == ["datastore"]

    def test_nulls_and_numbers_do_not_raise(self) -> None:
        plan = _plan({"entity_kinds": None, "symbols": [1, None, "ToolPool"], "paths": 7})

        assert plan.symbols == ["ToolPool"]
        assert plan.entity_kinds == []
        assert plan.paths == []

    def test_lists_are_capped(self) -> None:
        """A model that returns forty symbols should not produce forty traversals."""
        plan = _plan({"symbols": sorted(VOCAB.symbols) * 10})

        assert len(plan.symbols) <= 5

    def test_reasoning_is_bounded(self) -> None:
        plan = _plan({"reasoning": "x" * 5000})

        assert len(plan.reasoning) <= 300


class TestSearchQueries:
    """The rewrite is the thing a phrase table structurally cannot do."""

    def test_queries_are_kept_without_validation(self) -> None:
        """They are search strings, not claims about the repository. A poor one
        costs a weak ranking, not a wrong fact — so there is nothing to check them
        against."""
        plan = _plan({"search_queries": ["async engine creation", "connection pool"]})

        assert plan.search_queries == ["async engine creation", "connection pool"]

    def test_queries_are_capped(self) -> None:
        plan = _plan({"search_queries": [f"q{i}" for i in range(20)]})

        assert len(plan.search_queries) <= 3

    def test_empty_strings_are_discarded(self) -> None:
        plan = _plan({"search_queries": ["", "  ", "real query"]})

        assert plan.search_queries == ["real query"]


class TestProvenance:
    def test_a_validated_plan_records_that_a_model_routed_it(self) -> None:
        """A fallback route and a chosen one are not equally trustworthy, and the
        inspector must not blur them."""
        plan = _plan({"intents": ["semantic"]})

        assert plan.routed_by == "llm"
        assert "via=llm" in plan.describe()


class TestFallback:
    async def test_a_failed_call_falls_back_to_rules(self, monkeypatch) -> None:
        """A question returning nothing because a model timed out is worse than one
        routed by a crude rule."""
        planner = LLMQuestionPlanner(VOCAB)

        async def _fail(_question):
            return None

        monkeypatch.setattr(planner, "_ask", _fail)

        plan = await planner.plan("what calls `ToolPool`")

        assert plan.routed_by == "rules"
        assert "semantic" in plan.intents
        assert "ToolPool" in plan.symbols  # the rule-based router still found it

    async def test_the_fallback_still_routes_traversals(self, monkeypatch) -> None:
        planner = LLMQuestionPlanner(VOCAB)

        async def _fail(_question):
            return None

        monkeypatch.setattr(planner, "_ask", _fail)

        plan = await planner.plan("what breaks if I change the database")

        assert "graph" in plan.intents


class TestVocabularyIsOnlyWhatExists:
    def test_an_empty_vocabulary_drops_everything_proposed(self) -> None:
        """A knowledge base with no entities must not have questions routed to an
        empty store — that reads to a user as retrieval being broken."""
        planner = LLMQuestionPlanner(KBVocabulary())

        plan = planner._validate("q", {
            "entity_kinds": ["datastore"],
            "narrative_topics": ["architecture"],
            "symbols": ["ToolPool"],
            "paths": ["app/main.py"],
        })

        assert plan.entity_kinds == []
        assert plan.narrative_topics == []
        assert plan.symbols == []
        assert plan.paths == []
        assert plan.intents == ["semantic"]
