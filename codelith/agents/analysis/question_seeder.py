"""
Questions worth asking about *this* codebase.

The chat page opened with four hardcoded ones — "How is the database initialised?",
"Where is data stored?" — asked of a browser SDK that has neither. Generic suggestions
are worse than none: an empty box says nothing, while a wrong suggestion advertises
that the thing offering it has not read your code, on the one screen whose entire claim
is that it has.

**Written here because this is the only moment anything knows.** Analysis holds the
whole inventory in front of it — every module and its role, the routes and env vars and
entrypoints that were extracted, the narrative topics the evidence justified — and that
is exactly the material a good question is made of. By the time somebody opens the chat
page, all of it is in the database and none of it is in one place.

**The fast tier, once.** This is selection and phrasing over an inventory that has
already been built, not reasoning about code, and a question that reads slightly
awkwardly costs a great deal less than the quality-tier call it would take to polish.

**Never fatal.** A failure here costs a page of suggestions, not an analysis: the
questions are a convenience and the knowledge base is the product. Anything that goes
wrong leaves the list empty and the run continues, which is the same rule the diagram
stage follows.
"""

from __future__ import annotations

from typing import Any

from codelith.agents.base import BaseAgent
from codelith.core.cancellation import JobCancelled
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.llm.prompts.analysis_prompts import SUGGESTED_QUESTIONS
from codelith.tracing.artifacts import save_artifact

#: How many to ask for. Enough that the four shown on an empty page differ between
#: visits, few enough that one fast call produces them all without wandering.
_WANTED = 14

#: A question longer than this is a paragraph with a question mark, and reads badly
#: on one line of a suggestion list.
_MAX_CHARS = 110

#: Facts of each kind put in front of the model. The inventory is what makes a
#: question specific; the whole of it would be a prompt nobody can afford.
_FACTS_PER_KIND = 8


class QuestionSeederAgent(BaseAgent):
    name = "question_seeder_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="QuestionSeeder: writing questions worth asking",
            end_message="QuestionSeeder: complete",
        ) as t:
            await self._update_step(self.name, "running")

            try:
                questions = await self._write(state)
            except JobCancelled:
                raise  # must not be downgraded to "this stage failed"
            except Exception as exc:
                # A page of suggestions is not worth failing an analysis for.
                await self._emit_log(
                    "warning", f"QuestionSeeder: could not write questions ({exc})"
                )
                questions = []

            t.outputs(questions=len(questions))
            await self._update_step(
                self.name, "completed", {"questions": len(questions)}
            )
            return {"suggested_questions": questions}

    async def _write(self, state: dict[str, Any]) -> list[str]:
        kb_id = state.get("kb_id")
        project = state.get("project")
        if not kb_id or project is None:
            return []

        repos = KnowledgeRepositories.for_session(self.db)
        modules = await repos.modules.list_by_kb(kb_id, limit=40)

        # A sample per kind rather than everything: the inventory is what makes a
        # question specific, and the whole of it is a prompt nobody can afford.
        by_kind: dict[str, list[str]] = {}
        for kind in sorted(await repos.entities.kind_breakdown(kb_id)):
            rows = await repos.entities.list_by_kind(kb_id, kind, limit=_FACTS_PER_KIND)
            if rows:
                by_kind[kind] = [r.name for r in rows]

        messages = SUGGESTED_QUESTIONS.render(
            project_name=project.name,
            wanted=str(_WANTED),
            modules="\n".join(
                f"  {m.path} ({m.role}) — {(m.summary or '').strip()[:110]}"
                for m in modules
            )
            or "  (none recorded)",
            facts="\n".join(
                f"  {kind}: {', '.join(names)}" for kind, names in sorted(by_kind.items())
            )
            or "  (none extracted)",
            topics=", ".join(sorted(state.get("narrative_topics") or [])) or "(none)",
        )

        raw = await self._call_llm_json(messages, task_type="classify")
        save_artifact("question_seeder.raw_response", raw)
        questions = _coerce(raw)

        # Stored here rather than by the persister, the way the site planner stores
        # its own map: the persister writes aggregate stats, not every agent's output.
        if questions:
            await repos.bases.update(kb_id, suggested_questions_json=questions)
        return questions


def _coerce(raw: Any) -> list[str]:
    """
    The model's answer, reduced to a list of usable questions.

    Tolerant of shape — a bare list, or an object with the list under some key — and
    strict about content. Anything that is not a question is discarded rather than
    shown: this list is the first thing somebody reads on the chat page, and one
    statement among the questions makes the whole set look unconsidered.
    """
    if isinstance(raw, dict):
        raw = next((v for v in raw.values() if isinstance(v, list)), [])
    if not isinstance(raw, list):
        return []

    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        text = (item if isinstance(item, str) else (item or {}).get("question", "")) or ""
        text = " ".join(str(text).split()).strip()
        if not text.endswith("?") or len(text) > _MAX_CHARS or len(text) < 12:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= _WANTED:
            break
    return out


__all__ = ["QuestionSeederAgent"]
