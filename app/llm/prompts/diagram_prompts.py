from app.llm.prompts.base import PromptTemplate

ARCHITECTURE_DIAGRAM = PromptTemplate(
    system=(
        "You are a technical diagrammer. Generate Mermaid diagram syntax only — no prose, no code fences, "
        "no explanations. Start directly with the diagram type keyword (e.g. 'graph TD', 'flowchart LR')."
    ),
    user=(
        "Create a Mermaid architecture diagram for project '$project_name'.\n\n"
        "Services and components:\n$services_list\n\n"
        "Tech stack: $tech_stack\n\n"
        "Use 'graph TD' and show the main services with labeled arrows for their relationships."
    ),
)

SEQUENCE_DIAGRAM = PromptTemplate(
    system=(
        "You are a technical diagrammer. Generate Mermaid sequenceDiagram syntax only — "
        "no prose, no code fences, no explanations."
    ),
    user=(
        "Create a Mermaid sequence diagram for the main request flow in '$project_name'.\n\n"
        "Entry points: $entry_points\n"
        "Services: $services_list"
    ),
)
