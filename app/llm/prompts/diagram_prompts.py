"""
Diagram prompts.

One parameterised prompt rather than a fixed pair. Which diagrams get drawn is decided
by `DiagramAgent` from the document type and the facts the knowledge base holds, so the
prompt takes the kind of diagram, its purpose, and — critically — the vocabulary of
node labels it is allowed to use.

That last part is the fix for run 2, where an architecture diagram invented `Workers`,
`Storage`, `Data Ingestion`, `Update Model` and `Feedback Loop` for a codebase that has
none of them. Nodes must be named from real services, modules and routes, because a
diagram is read as fact.
"""

from app.llm.prompts.base import PromptTemplate

DIAGRAM = PromptTemplate(
    system=(
        "You are a technical diagrammer. Output Mermaid syntax ONLY — no prose, no code "
        "fences, no preamble, no explanation. The first line must be the diagram type "
        "keyword and nothing else.\n\n"
        "Required type for this diagram: $mermaid_type\n\n"
        "Rules:\n"
        "  - **Every node, participant or entity label must come from the allowed list "
        "below, copied exactly.** Do not invent components. If the list is too small to "
        "make an interesting diagram, draw the small diagram.\n"
        "  - Draw only relationships supported by the supplied facts or the document "
        "text. An invented arrow is a wrong diagram, not a helpful guess.\n"
        "  - Node IDs must be short and alphanumeric; put the real name in the label.\n"
        "  - Label arrows with what actually happens (calls, reads, writes, returns).\n"
        "  - No styling directives, no CSS blocks, no HTML. Structure only.\n"
        "  - Between 3 and 12 nodes. Prefer the clearest subset over completeness."
    ),
    user=(
        "Project: $project_name\n"
        "Diagram: $purpose\n\n"
        "Allowed node labels (use these exact names):\n$allowed_nodes\n\n"
        "Known relationships:\n$relations\n\n"
        "Supporting facts:\n$facts\n\n"
        "What the document says:\n$doc_excerpt"
    ),
)

DIAGRAM_REPAIR = PromptTemplate(
    system=(
        "You are fixing a Mermaid diagram that failed validation. Output the corrected "
        "Mermaid syntax ONLY — no prose, no code fences, no explanation. The first line "
        "must be the diagram type keyword.\n\n"
        "Keep the same content and the same node labels; change only what is needed to "
        "make it valid Mermaid of type $mermaid_type."
    ),
    user="Problem: $reason\n\nDiagram:\n$diagram",
)

__all__ = ["DIAGRAM", "DIAGRAM_REPAIR"]
