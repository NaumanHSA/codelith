"""
Mermaid validation.

Both diagrams run 2 produced would have rendered as error boxes. Nothing checked
them, and they were discarded for an unrelated reason. These are the exact failures.
"""

from __future__ import annotations

from app.tools.mermaid import clean_mermaid, validate_mermaid


class TestRealFailuresFromRun2:
    def test_css_style_block_is_rejected(self) -> None:
        diagram = "graph TD\n  A[X] --> B[Y]\n  style graph {\n    node fill #4a4a4a\n  }"
        result = validate_mermaid(diagram)
        assert not result.ok
        assert "CSS" in result.reason

    def test_conversational_preamble_is_rejected_when_it_survives_cleaning(self) -> None:
        result = validate_mermaid("mermaid diagram:\n    A[main] --> B(CLI)")
        assert not result.ok
        assert "no diagram type" in result.reason

    def test_ascii_tree_branches_are_rejected(self) -> None:
        diagram = "graph TD\n  A --> B\n  |--> C[Command Parsing]"
        assert not validate_mermaid(diagram).ok

    def test_inline_arrow_modifiers_are_rejected(self) -> None:
        assert not validate_mermaid("graph TD\n  A --async->B --style thick").ok


class TestValidDiagramsPass:
    def test_flowchart(self) -> None:
        assert validate_mermaid("graph TD\n  A[CLI] --> B[Server]\n  B --> C[(DB)]").ok

    def test_sequence(self) -> None:
        diagram = (
            "sequenceDiagram\n"
            "  participant C as Client\n"
            "  C->>S: POST /v1/chat/completions\n"
            "  S-->>C: 200 OK"
        )
        assert validate_mermaid(diagram).ok

    def test_class_diagram(self) -> None:
        assert validate_mermaid("classDiagram\n  Request <|-- ChatRequest").ok


class TestRejectsEmptiness:
    def test_empty(self) -> None:
        assert not validate_mermaid("").ok

    def test_type_without_a_body(self) -> None:
        result = validate_mermaid("graph TD")
        assert not result.ok
        assert "no body" in result.reason

    def test_body_using_the_wrong_syntax_for_its_type(self) -> None:
        """A sequence diagram made of flowchart arrows will not render as declared."""
        assert not validate_mermaid("sequenceDiagram\n  A[X] === B[Y]").ok


class TestCleaning:
    def test_strips_fences_and_language_tag(self) -> None:
        assert clean_mermaid("```mermaid\ngraph TD\n  A-->B\n```") == "graph TD\n  A-->B"

    def test_strips_preamble_before_the_type(self) -> None:
        raw = "Sure! Here is the diagram:\n\ngraph TD\n  A-->B"
        assert clean_mermaid(raw) == "graph TD\n  A-->B"

    def test_cleaned_output_of_a_valid_fenced_diagram_validates(self) -> None:
        assert validate_mermaid(clean_mermaid("```mermaid\ngraph LR\n  A-->B\n```")).ok


class TestClassDiagramStrictness:
    def test_class_declaration_with_free_text_is_rejected(self) -> None:
        """
        Produced live: `class Foo --` followed by indented prose. It contains `--`, so
        a loose rule accepted it, and it would have rendered as garbage.
        """
        diagram = (
            "classDiagram\n"
            "  class NeurosurferGateway --\n"
            "    connectsTo neurosurfer.vectorstores\n"
            "    routes GET, GET, POST/\n"
            # The real output also carried valid relations lower down, which is why a
            # whole-document check passed it.
            "  NeurosurferGateway --> NeurosurferAgent"
        )
        assert not validate_mermaid(diagram).ok

    def test_relationships_are_accepted(self) -> None:
        assert validate_mermaid("classDiagram\n  ChatRequest <|-- Request").ok

    def test_member_blocks_are_accepted(self) -> None:
        assert validate_mermaid("classDiagram\n  class Request {\n    +str model\n  }").ok
