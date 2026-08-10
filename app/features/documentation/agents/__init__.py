"""
Phase 2 agents — composing documents from an existing knowledge base.

These never read the repository: analysis already extracted, embedded and summarised
it, and by composition time the clone is gone. Everything comes from the KB and from
`code_chunks`, which is our copy of the source.

Order in the graph:

    kb_loader   → resolve the KB, unpack the requested doc types
    strategy    → audience, tone, whether diagrams are worth it
    planner     → sections with real `key_files` per doc type
    writer      → retrieve-then-write, one LLM call per section
    linker      → resolve [[page-slug]] refs to real routes (no LLM)
    diagram → qa → gate → formatter → publisher   [reused from the original pipeline]
"""

from app.features.documentation.agents.kb_loader import KBLoaderAgent
from app.features.documentation.agents.linker import LinkerAgent
from app.features.documentation.agents.planner import CompositionPlannerAgent
from app.features.documentation.agents.strategy import CompositionStrategyAgent
from app.features.documentation.agents.writer import CompositionWriterAgent

__all__ = [
    "KBLoaderAgent",
    "CompositionStrategyAgent",
    "CompositionPlannerAgent",
    "CompositionWriterAgent",
    "LinkerAgent",
]
