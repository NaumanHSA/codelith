"""The environment the code needs, against what any file declares (`knowledge/runbook.py`)."""

from __future__ import annotations

from sqlalchemy import select

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.knowledge.constants import EntityKind
from codelith.knowledge.runbook import RunbookService
from codelith.models.knowledge import KBEntity

AREAS = frozenset({"breaks"})
TITLE = "The environment the code needs"
RULES = {"breaks.env-undeclared": "Environment variables nothing declares"}


async def run(ctx: RunContext) -> list[Finding]:
    book = await RunbookService(ctx.db, ctx.kb).build()
    if not book.available:
        return []
    lines = {
        (name, source): line
        for name, source, line in (
            await ctx.db.execute(
                select(KBEntity.name, KBEntity.source_path, KBEntity.source_line).where(
                    KBEntity.kb_id == ctx.kb.id, KBEntity.kind == str(EntityKind.ENV_VAR)
                )
            )
        ).all()
    }
    scoped = {f.path for f in ctx.files}
    out: list[Finding] = []
    for env in book.env:
        if not env.missing:
            continue
        path = next((p for p in env.read_in if p in scoped), None)
        if path is None:
            continue
        out.append(
            Finding(
                rule="breaks.env-undeclared",
                area="breaks",
                severity="medium",
                title=f"The code needs `{env.name}`, and nothing declares it",
                message="It is read with no default, so the code fails without it, and no env template, compose "
                "file or Dockerfile says it exists: whoever sets this up next finds out when it crashes.",
                fix=f"Add `{env.name}=` to the env template with a comment saying what it is"
                + (" (it looks like a secret: no value in the template)" if env.secret else "")
                + ", or give it a default in the code.",
                path=path,
                line=lines.get((env.name, path)),
                source="check",
                evidence={"read_in": env.read_in},
            )
        )
    return out


__all__ = ["AREAS", "TITLE", "run"]
