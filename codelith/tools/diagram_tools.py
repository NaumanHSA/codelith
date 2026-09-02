import re

_VALID_STARTERS = (
    "graph", "flowchart", "sequencediagram", "classdiagram",
    "statediagram", "erdiagram", "gantt", "pie", "gitgraph",
)


def validate_mermaid(content: str) -> tuple[bool, str]:
    """Best-effort Mermaid syntax check without a renderer."""
    if not content or not content.strip():
        return False, "Empty diagram"

    first_line = content.strip().splitlines()[0].strip().lower()
    if not any(first_line.startswith(s) for s in _VALID_STARTERS):
        return False, f"Unrecognised diagram type: '{first_line}'"

    # Check for basic structural issues
    open_brackets = content.count("{")
    close_brackets = content.count("}")
    if abs(open_brackets - close_brackets) > 2:
        return False, "Unbalanced braces"

    return True, "OK"


def wrap_in_code_fence(content: str) -> str:
    return f"```mermaid\n{content.strip()}\n```"


def extract_node_names(mermaid_content: str) -> list[str]:
    """Pull node identifiers from a graph TD / flowchart diagram."""
    return re.findall(r'\b([A-Za-z_]\w*)\s*[\[({]', mermaid_content)
