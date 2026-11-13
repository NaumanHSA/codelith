"""
Knowledge Base repositories.

Grouped as a package because the KB has four related tables and the analysis
workflow touches all of them; `KnowledgeRepositories` bundles them so agents take
one dependency instead of four.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.commit_repo import CommitRepository
from codelith.db.repositories.knowledge.entity_repo import KBEntityRepository
from codelith.db.repositories.knowledge.knowledge_base_repo import KnowledgeBaseRepository
from codelith.db.repositories.knowledge.module_repo import KBModuleRepository
from codelith.db.repositories.knowledge.narrative_repo import KBNarrativeRepository
from codelith.db.repositories.knowledge.source_repo import SourceRepository


@dataclass(slots=True)
class KnowledgeRepositories:
    """Convenience bundle of the four KB repositories over one session."""

    bases: KnowledgeBaseRepository
    modules: KBModuleRepository
    entities: KBEntityRepository
    narratives: KBNarrativeRepository
    #: Each reading's files, the content stored once.
    sources: SourceRepository
    #: Each codebase's commits, for what moved between two readings.
    commits: CommitRepository

    @classmethod
    def for_session(cls, session: AsyncSession) -> KnowledgeRepositories:
        return cls(
            bases=KnowledgeBaseRepository(session),
            modules=KBModuleRepository(session),
            entities=KBEntityRepository(session),
            narratives=KBNarrativeRepository(session),
            sources=SourceRepository(session),
            commits=CommitRepository(session),
        )


__all__ = [
    "CommitRepository",
    "KnowledgeBaseRepository",
    "KBModuleRepository",
    "KBEntityRepository",
    "KBNarrativeRepository",
    "KnowledgeRepositories",
    "SourceRepository",
]
