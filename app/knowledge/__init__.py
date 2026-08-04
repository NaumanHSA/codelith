"""
Knowledge Base domain package.

A knowledge base is everything we understand about one project at one commit:
structured facts (routes, dependencies, entrypoints), a semantic index over the
source, and LLM-derived prose (module summaries, cross-cutting narratives).

It is built once by the analysis workflow and read repeatedly by composition, so
choosing a second document type costs no re-analysis.

Phase A ships the vocabulary and persistence; the analysis pipeline that fills a KB
lands in Phase B (see `.dev/PLAN.md`).
"""

from __future__ import annotations

from app.knowledge.constants import (
    EntityKind,
    JobType,
    KBStatus,
    ModuleRole,
    NarrativeTopic,
)

__all__ = ["EntityKind", "JobType", "KBStatus", "ModuleRole", "NarrativeTopic"]
