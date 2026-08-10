"""
Diagram prompts.

One parameterised prompt rather than a fixed pair. Which diagrams get drawn is decided
by `DiagramAgent` from the document type and the facts the knowledge base holds, so the
prompt takes the kind of diagram, its purpose, and — critically — the vocabulary of
node labels it is allowed to use.

That last part is the fix for run 2, where an architecture diagram invented `Workers`,
`Storage`, `Data Ingestion` and a `Feedback Loop` for a codebase that has none of them.
Nodes must be named from real services, modules and routes, because a diagram is read
as fact.

Each call also carries **one worked example of the requested diagram type**. Local
models reproduce a demonstrated shape far more reliably than they follow a description
of one, and the two failures worth preventing — CSS-shaped `style` blocks and ASCII
`|--` trees — are both cases of the model reaching for a syntax it half-remembers. The
examples are picked per type rather than concatenated so no call pays for all of them.
"""

from codelith.llm.prompts.base import PromptTemplate

#: Worked examples, keyed by the Mermaid type keyword the agent asks for. Each shows
#: the constructs that type actually supports: `classDef`/`subgraph` and labelled edges
#: for flowcharts, `participant`/`alt`/`opt` for sequences, members and relationships
#: for class diagrams.
EXAMPLES: dict[str, str] = {
    "graph": """flowchart TD
  classDef api fill:#e7f0ff,stroke:#5b8def,stroke-width:1px,color:#0b3b8c
  classDef proc fill:#f9f9f9,stroke:#777,stroke-width:1px
  classDef store fill:#fff6e6,stroke:#b37b00,stroke-width:1px

  subgraph S_SOURCES [Upstream Sources]
    DB[(Operational DB)]:::store
    FS[(File Store)]:::store
  end

  subgraph P_PRECOMP [Precompute Stage]
    direction LR
    P1[Load notings]:::proc
    P2[Normalize and parse notes]:::proc
    P3[Chunker notes_per_chunk = 80-150]:::proc
    P8[(State JSON)]:::store
  end

  A1[[POST /api/noting/summary]]:::api

  DB -->|rows: notings| P1
  FS -->|files| P1
  P1 --> P2
  P2 -->|normalized notings| P3
  P3 -->|chunks| P8
  A1 -->|file_id| P8
  P8 -->|cached final_summary_text| A1""",
    "flowchart": None,  # filled in below — same example as `graph`
    "sequencediagram": """sequenceDiagram
  actor Customer as User
  participant LoginPage as Log in page
  participant P1 as Log in details storage
  participant P2 as Security Department

  Customer ->>+ LoginPage: Input: Username
  LoginPage ->> P1: Username and password
  P1 ->> P1: Authenticate
  alt Successful Authentication
    LoginPage ->> LoginPage: Redirect to welcome page
    LoginPage ->> Customer: Log in successful, stand by
  else Failed Authentication
    P1 ->> LoginPage: If rejected
    LoginPage ->> Customer: Password Hint
  end

  opt Password Reset Flow
    Customer ->> LoginPage: Yes
    LoginPage ->> P2: New password request
    P2 ->> P2: Validate email address
    P2 ->> P1: Store new password
  end""",
    "classdiagram": """classDiagram
  class ChatRequest {
    +string model
    +Message[] messages
    +bool stream
  }
  class ChatResponse {
    +string id
    +Choice[] choices
  }
  class Message {
    +string role
    +string content
  }
  ChatRequest "1" *-- "many" Message : contains
  ChatRequest --> ChatResponse : produces""",
    "erdiagram": """erDiagram
  PROJECT ||--o{ SOURCE : has
  PROJECT ||--o{ JOB : runs
  JOB ||--|| KNOWLEDGE_BASE : produces
  KNOWLEDGE_BASE ||--o{ MODULE : contains""",
}
EXAMPLES["flowchart"] = EXAMPLES["graph"]


def example_for(mermaid_type: str) -> str:
    """The worked example matching a requested type, falling back to a flowchart."""
    key = (mermaid_type or "").split()[0].lower() if mermaid_type else ""
    return EXAMPLES.get(key) or EXAMPLES["graph"]


DIAGRAM = PromptTemplate(
    system=(
        "You are a technical diagrammer. Output Mermaid syntax ONLY — no prose, no code "
        "fences, no preamble, no explanation. The first line must be the diagram type "
        "keyword and nothing else.\n\n"
        "Required type for this diagram: $mermaid_type\n\n"
        "Below is a correct example **of the syntax only**. It describes a completely "
        "different, unrelated project. Copy its *shape* — the arrow forms, the node and "
        "participant declarations, the way blocks are opened and closed. Never copy a "
        "single one of its names: `LoginPage`, `Customer`, `P1`, `ChatRequest` and the "
        "rest do not exist in this codebase, and a diagram naming them is wrong.\n\n"
        "$example\n\n"
        "Rules:\n"
        "  - **Every node, participant or entity label must come from the allowed list "
        "below, copied exactly.** Do not invent components. If the list is too small to "
        "make an interesting diagram, draw the small diagram.\n"
        "  - Draw only relationships supported by the supplied facts or the document "
        "text. An invented arrow is a wrong diagram, not a helpful guess.\n"
        "  - Node and participant IDs must be short and alphanumeric — no dots, no "
        "slashes, no dashes. Put the real name in the label: `participant P1 as "
        "codelith.server.api` in sequence diagrams, `P1[app.server.api]` in flowcharts. A "
        "dotted id like `app.server.api ->> db:` is a parse error.\n"
        "  - Label arrows with what actually happens (calls, reads, writes, returns).\n"
        "  - Styling is allowed only through `classDef` and `:::class`, exactly as in "
        "the example. Never write CSS blocks, HTML, or `--style` on an arrow.\n"
        "  - Never draw ASCII trees with `|--`. Use the arrow forms from the example.\n"
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
        "Change only what is needed to make it valid Mermaid of type $mermaid_type, and "
        "make sure every label comes from the allowed list below. Drop any node whose "
        "name is not on that list rather than renaming it to something plausible.\n\n"
        "Allowed labels:\n$allowed_nodes\n\n"
        "A correct example of the syntax — its names belong to another project and must "
        "not appear in your output:\n\n$example"
    ),
    user="Problem: $reason\n\nDiagram:\n$diagram",
)

__all__ = ["DIAGRAM", "DIAGRAM_REPAIR", "EXAMPLES", "example_for"]
