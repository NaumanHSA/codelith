"""
Reading the architecture analysis wrote, and making it safe to draw.

The whole of this module is coercion, and that is the point. `architecture_json` is
model output stored verbatim, so every assumption a renderer would like to make about
it is one somebody's repository will break. A service with no name, a relation whose
`from` was never listed as a service, a `tech_stack` that came back as a string
instead of an object: all of these have to become something drawable or be dropped,
and none of them may raise.

The one thing that is *not* silently dropped is a relation pointing at a service that
does not exist. Those are counted and reported, because an edge to nowhere is a defect
in the analysis and hiding it entirely would mean nobody ever finds out.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.knowledge_base_repo import KnowledgeBaseRepository
from codelith.models.user import User
from codelith.schemas.architecture import (
    ArchitectureOut,
    ArchLayer,
    ArchRelation,
    ArchService,
    TechStack,
)
from codelith.services.project_service import ProjectService

logger = structlog.get_logger(__name__)

#: Keys the writer has used for the two ends of a relation. `from` is a Python
#: keyword, which is why the schema calls them source and target.
_SOURCE_KEYS = ("from", "source", "src")
_TARGET_KEYS = ("to", "target", "dst")


def _text(value: object, limit: int = 400) -> str:
    """Anything, as a bounded single-line string."""
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def _strings(value: object, limit: int = 60) -> list[str]:
    """A list of strings, from whatever shape arrived."""
    if isinstance(value, str):
        return [_text(value)] if value.strip() else []
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        # A list of objects is common when the writer decided each entry needed a
        # name and a note. Take the name.
        if isinstance(item, dict):
            item = item.get("name") or item.get("module") or item.get("path") or ""
        text = _text(item, 120)
        if text:
            out.append(text)
    return out[:limit]


def _items(value: object) -> list:
    """
    A list to iterate, whatever arrived.

    The outer `get` catches everything, but relying on that would mean one field of
    the wrong type costs the entire map. A service list that came back as a number
    should lose the services and keep the patterns.
    """
    return value if isinstance(value, list) else []


def _first(data: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if data.get(key):
            return _text(data[key], 120)
    return ""


class ArchitectureService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.projects = ProjectService(db)
        self.bases = KnowledgeBaseRepository(db)

    async def get(self, project_id: int, user: User) -> ArchitectureOut:
        """
        The architecture of the newest usable reading, or an empty answer.

        Empty rather than a 404: a project analysed before this column existed is not
        an error, and the page should say there is no map yet rather than fail.
        """
        await self.projects.get(project_id, user)

        kb = await self.bases.get_latest_usable(project_id)
        if kb is None:
            return ArchitectureOut(available=False)

        raw = kb.architecture_json or {}
        if not isinstance(raw, dict) or not raw:
            return ArchitectureOut(available=False, commit_sha=kb.commit_sha)

        try:
            return self._coerce(raw, kb.commit_sha)
        except Exception:  # noqa: BLE001 — a malformed column must not fail the page
            logger.warning("architecture_unreadable", project_id=project_id, kb_id=kb.id)
            return ArchitectureOut(available=False, commit_sha=kb.commit_sha)

    def _coerce(self, raw: dict, commit_sha: str | None) -> ArchitectureOut:
        services: list[ArchService] = []
        seen: set[str] = set()
        for item in _items(raw.get("services")):
            if not isinstance(item, dict):
                # A bare string is a service with a name and nothing else.
                name = _text(item, 120)
                if name and name not in seen:
                    seen.add(name)
                    services.append(ArchService(name=name))
                continue
            name = _text(item.get("name"), 120)
            if not name or name in seen:
                continue
            seen.add(name)
            services.append(
                ArchService(
                    name=name,
                    type=_text(item.get("type"), 32),
                    description=_text(item.get("description")),
                    modules=_strings(item.get("modules")),
                )
            )

        relations: list[ArchRelation] = []
        dangling = 0
        for item in _items(raw.get("relations")):
            if not isinstance(item, dict):
                continue
            source = _first(item, _SOURCE_KEYS)
            target = _first(item, _TARGET_KEYS)
            if not source or not target:
                continue
            # An edge whose ends are not on the diagram cannot be drawn. Counted so
            # the defect is visible rather than silently swallowed.
            if source not in seen or target not in seen:
                dangling += 1
                continue
            relations.append(
                ArchRelation(source=source, target=target, kind=_text(item.get("kind"), 32))
            )

        layers: list[ArchLayer] = []
        for item in _items(raw.get("layers")):
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"), 60)
            if name:
                layers.append(ArchLayer(name=name, modules=_strings(item.get("modules"))))

        stack_raw = raw.get("tech_stack")
        stack = TechStack()
        if isinstance(stack_raw, dict):
            stack = TechStack(
                language=_text(stack_raw.get("language"), 120),
                frameworks=_strings(stack_raw.get("frameworks"), 20),
                databases=_strings(stack_raw.get("databases"), 20),
                infra=_strings(stack_raw.get("infra"), 20),
            )

        return ArchitectureOut(
            # A map with no services is not a map. Everything else can be empty and
            # the page still has something to draw.
            available=bool(services),
            commit_sha=commit_sha,
            services=services,
            relations=relations,
            layers=layers,
            patterns=_strings(raw.get("patterns"), 20),
            entry_points=_strings(raw.get("entry_points"), 20),
            tech_stack=stack,
            dangling_relations=dangling,
        )


__all__ = ["ArchitectureService"]
