"""
Narrative topic vocabulary.

Run 1 wrote 6 of 10 topics and the misses were caused by our trigger tables rather
than by absent evidence. These pin the parts that must not regress: the floor is
evidence-driven, `error_handling` is reachable, and a model cannot introduce a topic
name that no consumer looks up.
"""

from __future__ import annotations

from codelith.knowledge.constants import EntityKind, ModuleRole, NarrativeTopic
from codelith.knowledge.narratives import (
    coerce_topics,
    required_topics,
    topics_for_doc_type,
)


class TestFloor:
    def test_overview_and_architecture_are_always_written(self) -> None:
        assert required_topics([], []) == [
            NarrativeTopic.OVERVIEW,
            NarrativeTopic.ARCHITECTURE,
        ]

    def test_error_handling_is_reachable(self) -> None:
        """
        It was in the enum with prompt guidance written for it, and in no trigger
        table at all — so no codebase could produce it.
        """
        topics = required_topics([str(ModuleRole.SERVICE)], [])
        assert NarrativeTopic.ERROR_HANDLING in topics

    def test_env_vars_force_the_configuration_story(self) -> None:
        topics = required_topics([], [str(EntityKind.ENV_VAR)])
        assert NarrativeTopic.CONFIGURATION in topics

    def test_routes_force_the_request_lifecycle(self) -> None:
        topics = required_topics([], [str(EntityKind.ROUTE)])
        assert NarrativeTopic.REQUEST_LIFECYCLE in topics

    def test_a_cli_project_gets_a_cli_narrative(self) -> None:
        assert NarrativeTopic.CLI_USAGE in required_topics([str(ModuleRole.CLI)], [])

    def test_auth_comes_from_module_names(self) -> None:
        assert NarrativeTopic.AUTH in required_topics([], [], ["app/auth", "app/core"])

    def test_auth_is_not_triggered_by_the_word_token(self) -> None:
        """`token` fired on tokenizers, JWT helpers and anything counting tokens."""
        assert NarrativeTopic.AUTH not in required_topics([], [], ["app/tokenizer"])

    def test_no_duplicates_when_several_signals_agree(self) -> None:
        topics = required_topics(
            [str(ModuleRole.CONFIG)], [str(EntityKind.ENV_VAR)]
        )
        assert len(topics) == len(set(topics))


class TestDocTypeMapping:
    def test_an_api_document_reads_the_narrative_holding_its_endpoints(self) -> None:
        """
        The run 2 failure in one assertion: strategy hardcoded overview + architecture,
        so the endpoint list in `request_lifecycle` was never passed to it.
        """
        assert NarrativeTopic.REQUEST_LIFECYCLE in topics_for_doc_type("api")

    def test_deployment_reads_configuration(self) -> None:
        assert NarrativeTopic.CONFIGURATION in topics_for_doc_type("deployment")

    def test_an_unknown_doc_type_still_gets_something(self) -> None:
        assert topics_for_doc_type("wat") == (
            NarrativeTopic.OVERVIEW,
            NarrativeTopic.ARCHITECTURE,
        )

    def test_every_mapped_topic_is_a_real_enum_member(self) -> None:
        """A mapping typo would silently mean "this document gets no narrative"."""
        for doc_type in ("api", "architecture", "deployment", "getting_started", "modules"):
            for topic in topics_for_doc_type(doc_type):
                assert topic in set(NarrativeTopic)


class TestCoercion:
    def test_model_output_is_mapped_onto_the_enum(self) -> None:
        assert coerce_topics(["auth", "Testing", "data-model"]) == [
            NarrativeTopic.AUTH,
            NarrativeTopic.TESTING,
            NarrativeTopic.DATA_MODEL,
        ]

    def test_invented_topics_are_discarded(self) -> None:
        """
        Otherwise an API document asks for `auth`, finds nothing, and is written
        without it — with no error anywhere.
        """
        assert coerce_topics(["authentication_and_permissions", "vibes"]) == []

    def test_duplicates_collapse(self) -> None:
        assert coerce_topics(["auth", "AUTH", "auth"]) == [NarrativeTopic.AUTH]
