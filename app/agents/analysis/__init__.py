"""
Phase 1 agents — building the knowledge base.

These run before any document type is chosen. Their output is deliberately
doc-type-independent so composition can reuse it for an architecture guide, an API
reference or a tutorial without re-analysing anything.

Order in the graph:

    structured_extractor  → deterministic facts (no LLM)
    semantic_indexer      → embeddings into pgvector (no chat LLM)
    module_summarizer     → per-module prose        (LLM, concurrent)
    architecture_synthesizer → architecture map     (LLM, one call)
    narrative_writer      → cross-cutting prose     (LLM, concurrent)
    site_planner          → the site map            (LLM, one call)
    kb_persister          → stats + READY/DEGRADED  (no LLM)

`site_planner` is the one that outlives the knowledge base: everything else here
describes the code, while it proposes the *documentation site* the code warrants,
and its slugs become permanent URLs the moment they are merged.
"""

from app.agents.analysis.architecture_synthesizer import ArchitectureSynthesizerAgent
from app.agents.analysis.graph_builder import GraphBuilderAgent
from app.agents.analysis.kb_persister import KBPersisterAgent
from app.agents.analysis.module_summarizer import ModuleSummarizerAgent
from app.agents.analysis.narrative_writer import NarrativeWriterAgent
from app.agents.analysis.semantic_indexer import SemanticIndexerAgent
from app.agents.analysis.site_planner import SitePlannerAgent
from app.agents.analysis.structured_extractor import StructuredExtractorAgent

__all__ = [
    "StructuredExtractorAgent",
    "SemanticIndexerAgent",
    "ModuleSummarizerAgent",
    "ArchitectureSynthesizerAgent",
    "NarrativeWriterAgent",
    "SitePlannerAgent",
    "GraphBuilderAgent",
    "KBPersisterAgent",
]
