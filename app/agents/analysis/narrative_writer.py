"""
Cross-cutting narratives.

Prose that is true of the codebase regardless of which document the user eventually
asks for — an overview, how a request flows, how auth works. Written once here and
reused by every composition, which is the whole point of splitting analysis out.

Topics are chosen from the evidence: there is no reason to spend a call writing about
authentication in a project that has none.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.agents.base import BaseAgent
from app.config import get_settings
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import EntityKind, ModuleRole, NarrativeTopic
from app.llm.prompts.analysis_prompts import NARRATIVE, TOPIC_GUIDANCE

#: Sentinel the prompt asks for when a topic does not apply to this codebase.
_NOT_APPLICABLE = "NOT_APPLICABLE"

#: How much of each module summary survives into a downstream prompt.
_SUMMARY_CHARS = 400

#: Topics always attempted — every codebase can be described and structured.
_ALWAYS = (NarrativeTopic.OVERVIEW, NarrativeTopic.ARCHITECTURE)

#: Topic → module roles that make it worth writing.
_ROLE_TRIGGERS: dict[NarrativeTopic, set[ModuleRole]] = {
    NarrativeTopic.REQUEST_LIFECYCLE: {ModuleRole.API, ModuleRole.SERVICE, ModuleRole.WORKER},
    NarrativeTopic.DATA_MODEL: {ModuleRole.MODEL, ModuleRole.DATA_ACCESS, ModuleRole.SCHEMA},
    NarrativeTopic.CONFIGURATION: {ModuleRole.CONFIG},
    NarrativeTopic.TESTING: {ModuleRole.TEST},
    NarrativeTopic.DEPLOYMENT: {ModuleRole.INFRA},
}

#: Topic → entity kinds that make it worth writing.
_ENTITY_TRIGGERS: dict[NarrativeTopic, set[EntityKind]] = {
    NarrativeTopic.DEPLOYMENT: {EntityKind.INFRA_RESOURCE},
    NarrativeTopic.CONFIGURATION: {EntityKind.ENV_VAR},
    NarrativeTopic.INTEGRATIONS: {EntityKind.EXTERNAL_API},
}

#: Substrings in module names that suggest an auth story worth telling.
_AUTH_HINTS = ("auth", "security", "permission", "rbac", "identity", "login", "token")


class NarrativeWriterAgent(BaseAgent):
    name = "narrative_writer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="NarrativeWriter: writing cross-cutting narratives",
            end_message="NarrativeWriter: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            kb_id = state["kb_id"]
            architecture_map = state.get("architecture_map") or {}
            repos = KnowledgeRepositories.for_session(self.db)

            modules = await repos.modules.list_by_kb(kb_id, include_tests=True)
            entity_kinds = await repos.entities.kind_breakdown(kb_id)
            topics = self._select_topics(modules, entity_kinds)

            await self._emit_log(
                "info", f"Writing {len(topics)} narratives", topics=[str(x) for x in topics]
            )

            # Gather the supporting facts up front, sequentially. An AsyncSession
            # cannot be used from concurrent tasks — doing the reads inside the
            # gather below raises "another operation is in progress" and silently
            # loses narratives.
            facts_by_topic = {
                topic: await self._facts(topic, repos, kb_id, entity_kinds)
                for topic in topics
            }

            semaphore = asyncio.Semaphore(get_settings().ANALYSIS_SUMMARY_CONCURRENCY)

            async def write(topic: NarrativeTopic) -> tuple[NarrativeTopic, str | None]:
                async with semaphore:
                    return topic, await self._write(
                        topic, project, architecture_map, modules, facts_by_topic[topic]
                    )

            results = await asyncio.gather(*(write(x) for x in topics), return_exceptions=True)

            written = skipped = failed = 0
            # gather preserves order, so results line up with `topics` — which lets a
            # failure name the topic that caused it instead of vanishing into a count.
            for topic, outcome in zip(topics, results, strict=True):
                if isinstance(outcome, BaseException):
                    await self._emit_log(
                        "error",
                        f"Narrative '{topic}' raised {type(outcome).__name__}: {outcome}",
                    )
                    failed += 1
                    continue
                topic, content = outcome
                if content is None:
                    failed += 1
                elif content == _NOT_APPLICABLE:
                    skipped += 1
                else:
                    await repos.narratives.upsert(
                        kb_id, topic, content, {"generated_by": self.name}
                    )
                    written += 1
            await self.db.commit()

            await self._emit_log(
                "info", f"Wrote {written} narratives", skipped=skipped, failed=failed
            )
            t.outputs(written=written, skipped=skipped, failed=failed)
            await self._update_step(
                self.name, "completed",
                {"written": written, "skipped": skipped, "failed": failed},
            )

            return {"narratives_written": written, "narrative_failures": failed}

    # ── Topic selection ───────────────────────────────────────────────────────

    def _select_topics(self, modules, entity_kinds: dict[str, int]) -> list[NarrativeTopic]:
        roles = {ModuleRole(m.role) for m in modules if m.role in {str(r) for r in ModuleRole}}
        present_kinds = {k for k, count in entity_kinds.items() if count}

        topics = list(_ALWAYS)
        for topic, triggers in _ROLE_TRIGGERS.items():
            if roles & triggers:
                topics.append(topic)
        for topic, kinds in _ENTITY_TRIGGERS.items():
            if present_kinds & {str(k) for k in kinds} and topic not in topics:
                topics.append(topic)

        names = " ".join(m.name.lower() for m in modules)
        if any(hint in names for hint in _AUTH_HINTS):
            topics.append(NarrativeTopic.AUTH)

        # Preserve declaration order while de-duplicating.
        return list(dict.fromkeys(topics))

    # ── Writing ───────────────────────────────────────────────────────────────

    async def _write(self, topic, project, architecture_map, modules, facts: str) -> str | None:
        """Pure LLM step — no database access, so it is safe to run concurrently."""
        relevant = self._relevant_modules(topic, modules)
        messages = NARRATIVE.render(
            topic=str(topic),
            topic_guidance=TOPIC_GUIDANCE.get(str(topic), ""),
            project_name=project.name,
            architecture_json=json.dumps(architecture_map, indent=2)[:2500],
            module_inventory=self._inventory(relevant),
            facts=facts,
        )
        try:
            content = (await self._call_llm(messages, task_type="write") or "").strip()
        except Exception as exc:
            await self._emit_log("warning", f"Narrative '{topic}' failed: {exc}")
            return None

        if not content:
            return None
        return _NOT_APPLICABLE if content.upper().startswith(_NOT_APPLICABLE) else content

    @staticmethod
    def _relevant_modules(topic, modules, limit: int = 25):
        triggers = _ROLE_TRIGGERS.get(topic)
        if not triggers:
            return [m for m in modules if m.role != str(ModuleRole.TEST)][:limit]
        wanted = {str(r) for r in triggers}
        scoped = [m for m in modules if m.role in wanted]
        return (scoped or modules)[:limit]

    @staticmethod
    def _inventory(modules) -> str:
        lines = []
        for m in modules:
            summary = (m.summary or "").strip().replace("\n", " ")
            if len(summary) > _SUMMARY_CHARS:
                summary = summary[: _SUMMARY_CHARS - 3] + "..."
            lines.append(f"  {m.name} [{m.role}]" + (f" — {summary}" if summary else ""))
        return "\n".join(lines) or "  (no modules)"

    @staticmethod
    async def _facts(topic, repos, kb_id: int, entity_kinds: dict[str, int]) -> str:
        """Entity detail relevant to this topic, so claims stay grounded."""
        wanted: tuple[EntityKind, ...] = {
            NarrativeTopic.REQUEST_LIFECYCLE: (EntityKind.ROUTE, EntityKind.ENTRYPOINT),
            NarrativeTopic.DEPLOYMENT: (EntityKind.INFRA_RESOURCE, EntityKind.ENV_VAR),
            NarrativeTopic.CONFIGURATION: (EntityKind.ENV_VAR, EntityKind.CONFIG_FILE),
            NarrativeTopic.AUTH: (EntityKind.ROUTE,),
            NarrativeTopic.INTEGRATIONS: (EntityKind.EXTERNAL_API, EntityKind.DEPENDENCY),
        }.get(topic, (EntityKind.ENTRYPOINT, EntityKind.DEPENDENCY))

        blocks: list[str] = [f"Fact counts: {entity_kinds or '{}'}"]
        for kind in wanted:
            items = await repos.entities.list_by_kind(kb_id, kind, limit=30)
            if items:
                rendered = ", ".join(i.name for i in items[:30])
                blocks.append(f"{kind}: {rendered}")
        return "\n".join(blocks)
