"""
Reading the narratives analysis wrote.

Twelve of these are written per codebase, three thousand words of the longest, and
until now the only thing the product did with them was print their topic names as
chips. This reads them back in an order a person would read them in, with the brief
the writer was given and whatever it recorded about its sources.

Unlike `architecture_service`, almost nothing here is coercion: these are two text
columns, not model-written JSON. The one judgement is ordering, and it is not
alphabetical - "architecture" first and "auth" second is an accident of the alphabet,
not a reading order.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.knowledge_base_repo import KnowledgeBaseRepository
from codelith.db.repositories.knowledge.narrative_repo import KBNarrativeRepository
from codelith.knowledge.constants import NarrativeTopic
from codelith.llm.prompts.analysis_prompts import TOPIC_GUIDANCE
from codelith.models.user import User
from codelith.schemas.narrative import NarrativeOut, NarrativeProvenance, NarrativesOut
from codelith.services.project_service import ProjectService

#: The enum's own declaration order, which reads as an orientation: what the project
#: is, then how it is built, then how it runs. `list_by_kb` sorts by topic name, and
#: alphabetical puts "auth" second and "overview" tenth.
_ORDER = {str(topic): i for i, topic in enumerate(NarrativeTopic)}

#: Words that lose their meaning when title-cased. Everything else is fine as
#: "request lifecycle" with a capital R.
_ACRONYMS = {"cli": "CLI", "api": "API", "ui": "UI", "db": "DB", "http": "HTTP"}


def _title(topic: str) -> str:
    words = topic.replace("_", " ").split()
    if not words:
        return topic
    out = [_ACRONYMS.get(w.lower(), w) for w in words]
    # Capitalise the first word unless it is an acronym that is already shouting.
    if out[0] == words[0]:
        out[0] = out[0][:1].upper() + out[0][1:]
    return " ".join(out)


def _brief(topic: str) -> str:
    """The first sentence of what the writer was asked for. The rest is instruction
    to a model - paragraph counts and tone - and means nothing to a reader."""
    guidance = TOPIC_GUIDANCE.get(topic, "")
    head = guidance.split(". ")[0].strip()
    return head + "." if head and not head.endswith(".") else head


def _provenance(refs: object) -> NarrativeProvenance:
    if not isinstance(refs, dict):
        return NarrativeProvenance()
    return NarrativeProvenance(
        generated_by=str(refs.get("generated_by") or ""),
        modules=[str(m) for m in refs.get("modules") or [] if str(m).strip()][:40],
        facts=[str(f) for f in refs.get("facts") or [] if str(f).strip()][:20],
    )


def assemble(rows, commit_sha: str | None) -> NarrativesOut:
    """
    Narrative rows as the page wants them.

    A module-level function rather than a method because it touches nothing on the
    service, and because a test that has to reassemble this to exercise it would keep
    passing after the ordering below was removed.
    """
    items = [
        NarrativeOut(
            topic=row.topic,
            title=_title(row.topic),
            brief=_brief(row.topic),
            content_md=row.content_md or "",
            words=len((row.content_md or "").split()),
            provenance=_provenance(row.source_refs_json),
        )
        for row in rows
        # A row with no prose behind it would open an empty reader.
        if (row.content_md or "").strip()
    ]
    # A topic the enum has never heard of sorts last rather than breaking the
    # ordering; the writer coerces onto the enum, but the column does not.
    items.sort(key=lambda n: (_ORDER.get(n.topic, len(_ORDER)), n.topic))

    return NarrativesOut(available=bool(items), commit_sha=commit_sha, narratives=items)


class NarrativeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.projects = ProjectService(db)
        self.bases = KnowledgeBaseRepository(db)
        self.narratives = KBNarrativeRepository(db)

    async def list_for_project(self, project_id: int, user: User) -> NarrativesOut:
        """
        Every narrative on the newest usable reading, in reading order.

        Empty rather than 404 for the same reason the architecture map is: a project
        with no narratives yet is not an error, and the page says so itself.
        """
        await self.projects.get(project_id, user)

        kb = await self.bases.get_latest_usable(project_id)
        if kb is None:
            return NarrativesOut(available=False)

        rows = await self.narratives.list_by_kb(kb.id)
        return assemble(rows, kb.commit_sha)


__all__ = ["NarrativeService", "assemble"]
