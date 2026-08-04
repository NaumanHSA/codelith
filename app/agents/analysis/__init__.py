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
    kb_persister          → stats + READY/DEGRADED  (no LLM)
"""

from app.agents.analysis.architecture_synthesizer import ArchitectureSynthesizerAgent
from app.agents.analysis.kb_persister import KBPersisterAgent
from app.agents.analysis.module_summarizer import ModuleSummarizerAgent
from app.agents.analysis.narrative_writer import NarrativeWriterAgent
from app.agents.analysis.semantic_indexer import SemanticIndexerAgent
from app.agents.analysis.structured_extractor import StructuredExtractorAgent

__all__ = [
    "StructuredExtractorAgent",
    "SemanticIndexerAgent",
    "ModuleSummarizerAgent",
    "ArchitectureSynthesizerAgent",
    "NarrativeWriterAgent",
    "KBPersisterAgent",
]
