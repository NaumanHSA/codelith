"""
Cross-cutting narratives.

Prose that is true of the codebase regardless of which document the user eventually
asks for — an overview, how a request flows, how auth works. Written once here and
reused by every composition, which is the whole point of splitting analysis out.

Topic choice is two-part. `app.knowledge.narratives.required_topics()` supplies a
floor of topics the extracted facts plainly justify, and one cheap selection call on
the fast tier proposes anything further the evidence supports. The floor wins ties:
24 env vars mean this project has a configuration story whether or not a model
thought to mention it, and a bad selection call must cost quality rather than
silently drop a topic the facts demand.

Choosing before writing is also the cheaper order. Previously every heuristically
triggered topic was written on the quality tier and *then* possibly declined with
NOT_APPLICABLE — paying the expensive call to find out it was not wanted.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Any

from codelith.agents.base import BaseAgent
from codelith.config import get_settings
from codelith.core.cancellation import JobCancelled
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.constants import EntityKind, ModuleRole, NarrativeTopic
from codelith.knowledge.narratives import ROLE_TRIGGERS, coerce_topics, required_topics
from codelith.llm.prompts.analysis_prompts import NARRATIVE, TOPIC_GUIDANCE, TOPIC_SELECTION
from codelith.tracing.artifacts import save_artifact, save_text_artifact

#: Sentinel the prompt asks for when a topic does not apply to this codebase.
_NOT_APPLICABLE = "NOT_APPLICABLE"

#: How much of each module summary survives into a downstream prompt.
_SUMMARY_CHARS = 400


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
            topics = await self._choose_topics(
                project, architecture_map, modules, entity_kinds
            )

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

            for outcome in results:
                if isinstance(outcome, JobCancelled):
                    raise outcome

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
                    save_text_artifact(f"narrative_writer.{topic}", content)
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

    async def _choose_topics(
        self, project, architecture_map: dict, modules, entity_kinds: dict[str, int]
    ) -> list[NarrativeTopic]:
        """
        Floor first, then whatever the selector can justify on top of it.

        The floor is deterministic and non-negotiable. The selection call is allowed to
        *add* topics — it is the part that spots a plugin system or a concurrency story
        no keyword table anticipated — and its output is coerced onto the enum, so a
        model that invents a topic name simply has it dropped rather than writing a
        narrative no consumer will ever look up.
        """
        settings = get_settings()
        roles = [m.role for m in modules]
        present_kinds = [k for k, count in entity_kinds.items() if count]

        floor = required_topics(roles, present_kinds, [m.name for m in modules])
        proposed = await self._propose_topics(
            project, architecture_map, modules, roles, entity_kinds
        )

        extra = [t for t in proposed if t not in floor]
        topics = (floor + extra)[: settings.ANALYSIS_MAX_NARRATIVES]

        save_artifact(
            "narrative_writer.topic_selection",
            {
                "floor": [str(t) for t in floor],
                "proposed": [str(t) for t in proposed],
                "written": [str(t) for t in topics],
                "cap": settings.ANALYSIS_MAX_NARRATIVES,
            },
        )
        return topics

    async def _propose_topics(
        self, project, architecture_map: dict, modules, roles: list[str], entity_kinds: dict
    ) -> list[NarrativeTopic]:
        """One fast-tier call. A failure here costs nothing — the floor still stands."""
        catalogue = "\n".join(
            f"  {topic} — {TOPIC_GUIDANCE.get(str(topic), '').split('.')[0]}."
            for topic in NarrativeTopic
        )
        messages = TOPIC_SELECTION.render(
            project_name=project.name,
            topics=catalogue,
            architecture_json=json.dumps(architecture_map, indent=2)[:2000],
            roles=json.dumps(dict(Counter(roles))),
            facts=json.dumps(entity_kinds),
            module_inventory=self._inventory(modules[:30]),
        )
        try:
            # Quality tier: this is judgement about a codebase, not classification.
            response = await self._call_llm_json(messages, task_type="select")
        except JobCancelled:
            raise
        except Exception as exc:
            await self._emit_log("warning", f"Topic selection failed, using floor only: {exc}")
            return []

        if not isinstance(response, dict):
            return []
        chosen = [
            entry.get("topic")
            for entry in response.get("topics") or []
            if isinstance(entry, dict) and float(entry.get("confidence", 1.0) or 0) >= 0.5
        ]
        return coerce_topics(chosen)

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
        except JobCancelled:
            raise
        except Exception as exc:
            await self._emit_log("warning", f"Narrative '{topic}' failed: {exc}")
            return None

        if not content:
            return None
        return _NOT_APPLICABLE if content.upper().startswith(_NOT_APPLICABLE) else content

    @staticmethod
    def _relevant_modules(topic, modules, limit: int = 25):
        triggers = ROLE_TRIGGERS.get(topic)
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
