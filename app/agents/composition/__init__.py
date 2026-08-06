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

from app.agents.composition.kb_loader import KBLoaderAgent
from app.agents.composition.linker import LinkerAgent
from app.agents.composition.planner import CompositionPlannerAgent
from app.agents.composition.strategy import CompositionStrategyAgent
from app.agents.composition.writer import CompositionWriterAgent

__all__ = [
    "KBLoaderAgent",
    "CompositionStrategyAgent",
    "CompositionPlannerAgent",
    "CompositionWriterAgent",
    "LinkerAgent",
]
