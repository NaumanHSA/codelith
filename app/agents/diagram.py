"""
Diagrams, derived from the document that was written.

The previous agent made exactly two calls with hardcoded names — `Architecture
Overview` and `Request Flow` — whatever the document type, the plan or the content.
Run 2 shows what that produced: both diagrams were drawn from an empty architecture
map, so the model invented `Workers`, `Storage`, `Data Ingestion` and a `Feedback
Loop` for a codebase containing none of them; neither output was valid Mermaid; and
because `_inject_diagrams()` only fired for `architecture` documents, both were
silently discarded from the API document they were generated for.

Three changes:

  * **The set is derived.** Each document type has candidate diagrams, each gated by
    a precondition over the knowledge base. No routes means no request sequence. Zero
    diagrams is an ordinary outcome, which subsumes the "make diagrams opt-in" task.
  * **Nodes are grounded.** The prompt is given the exact vocabulary it may label
    nodes with — real service names, module names, routes — plus the `relations`
    edges the architecture map now carries.
  * **Nothing unrenderable ships.** Output is validated, repaired once, and dropped if
    it still fails.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from app.agents.base import BaseAgent
from app.config import get_settings
from app.core.cancellation import JobCancelled
from app.knowledge.constants import EntityKind
from app.llm.prompts.diagram_prompts import DIAGRAM, DIAGRAM_REPAIR, example_for
from app.tools.mermaid import clean_mermaid, ungrounded_labels, validate_mermaid
from app.tools.mermaid_render import render_png
from app.tracing.artifacts import save_text_artifact


@dataclass(slots=True)
class DiagramSpec:
    """One candidate diagram: what it depicts, how, and what makes it worth drawing."""

    key: str
    name: str
    mermaid_type: str
    purpose: str
    #: Minimum evidence. Checked against the KB before any call is made.
    needs_services: int = 0
    needs_routes: int = 0
    needs_infra: int = 0
    needs_data_modules: int = 0


#: Candidates per document type. Order matters — the first that qualifies is drawn
#: first, and the per-document cap is applied in order.
_CANDIDATES: dict[str, tuple[DiagramSpec, ...]] = {
    "architecture": (
        DiagramSpec(
            key="components", name="Component Map", mermaid_type="graph TD",
            purpose="how the services fit together and what calls what",
            needs_services=2,
        ),
        DiagramSpec(
            key="request_sequence", name="Request Flow", mermaid_type="sequenceDiagram",
            purpose="one request travelling through the system, hop by hop",
            needs_routes=1,
        ),
    ),
    "api": (
        DiagramSpec(
            key="request_sequence", name="Request Flow", mermaid_type="sequenceDiagram",
            purpose="a client request through the real endpoints to a response",
            needs_routes=1,
        ),
        DiagramSpec(
            key="schemas", name="Request and Response Shapes", mermaid_type="classDiagram",
            purpose="the request and response types the API exchanges",
            needs_data_modules=1,
        ),
    ),
    "deployment": (
        DiagramSpec(
            key="deployment", name="Deployment Topology", mermaid_type="graph LR",
            purpose="the services, containers and infrastructure this runs on",
            needs_infra=1,
        ),
    ),
    "modules": (
        DiagramSpec(
            key="components", name="Module Map", mermaid_type="graph TD",
            purpose="how the modules depend on one another",
            needs_services=2,
        ),
    ),
    "getting_started": (
        DiagramSpec(
            key="request_sequence", name="First Run", mermaid_type="sequenceDiagram",
            purpose="what happens when someone runs this for the first time",
            needs_routes=1,
        ),
    ),
}

#: Diagrams per document. Two is already a lot in a reference document.
_MAX_PER_DOC = 2

#: How much of the finished document the diagram is allowed to read.
_DOC_EXCERPT_CHARS = 2500


class DiagramAgent(BaseAgent):
    name = "diagram_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="DiagramAgent: choosing and drawing diagrams",
            end_message="DiagramAgent: complete",
        ) as t:
            await self._update_step(self.name, "running")

            if not get_settings().DIAGRAMS_ENABLED:
                await self._emit_log("info", "DiagramAgent: disabled (DIAGRAMS_ENABLED)")
                t.outputs(diagrams=0, disabled=True)
                await self._update_step(self.name, "completed", {"diagrams": 0, "disabled": True})
                return {"diagrams": []}

            strategy: dict = state.get("strategy") or {}
            if not strategy.get("generate_diagrams", True):
                await self._emit_log("info", "DiagramAgent: skipped (strategy: no diagrams)")
                t.outputs(diagrams=0, skipped=True)
                await self._update_step(self.name, "completed", {"diagrams": 0, "skipped": True})
                return {"diagrams": []}

            project = state["project"]
            architecture_map: dict = state.get("architecture_map") or {}
            generated_docs: list[dict] = state.get("generated_docs") or []
            sandbox = state.get("sandbox")

            vocabulary = await self._vocabulary(state, architecture_map)

            diagrams: list[dict] = []
            for doc in generated_docs:
                doc_type = doc.get("doc_type") or "architecture"
                specs = self._specs_for(doc_type, vocabulary)
                if not specs:
                    await self._emit_log(
                        "info", f"No diagram warranted for {doc_type} — evidence too thin"
                    )
                    continue
                for spec in specs:
                    drawn = await self._draw(spec, project, vocabulary, doc)
                    if drawn:
                        diagrams.append(drawn)

            self._persist(diagrams, sandbox)

            for d in diagrams:
                save_text_artifact(f"diagram.{d['doc_type']}.{d['name']}", d["content"], ext="mmd")

            t.outputs(
                diagrams=len(diagrams),
                kinds=[d["key"] for d in diagrams],
                rendered=sum(1 for d in diagrams if d.get("png_base64")),
            )
            await self._update_step(self.name, "completed", {"diagrams": len(diagrams)})
            await self._emit_log("info", "Diagrams generated", count=len(diagrams))
            return {"diagrams": diagrams}

    # ── Choosing ──────────────────────────────────────────────────────────────

    @staticmethod
    def _specs_for(doc_type: str, vocab: dict) -> list[DiagramSpec]:
        """Candidates whose evidence preconditions the knowledge base actually meets."""
        qualified: list[DiagramSpec] = []
        for spec in _CANDIDATES.get(doc_type, ()):
            if (
                len(vocab["services"]) >= spec.needs_services
                and len(vocab["routes"]) >= spec.needs_routes
                and len(vocab["infra"]) >= spec.needs_infra
                and len(vocab["data_modules"]) >= spec.needs_data_modules
            ):
                qualified.append(spec)
        return qualified[:_MAX_PER_DOC]

    async def _vocabulary(self, state: dict, architecture_map: dict) -> dict:
        """
        The only labels a diagram may use, drawn from what analysis actually found.

        Falls back to module names when the architecture map names no services, so a
        degraded map produces a smaller diagram rather than an invented one.
        """
        from app.db.repositories.knowledge import KnowledgeRepositories

        kb_id = state.get("kb_id")
        services = [
            s.get("name") for s in (architecture_map.get("services") or []) if s.get("name")
        ]
        relations = [
            r for r in (architecture_map.get("relations") or [])
            if isinstance(r, dict) and r.get("from") and r.get("to")
        ]

        routes: list[str] = []
        infra: list[str] = []
        modules: list[str] = []
        data_modules: list[str] = []

        if kb_id:
            repos = KnowledgeRepositories.for_session(self.db)
            routes = [e.name for e in await repos.entities.list_by_kind(
                kb_id, EntityKind.ROUTE, limit=20)]
            infra = [e.name for e in await repos.entities.list_by_kind(
                kb_id, EntityKind.INFRA_RESOURCE, limit=20)]
            all_modules = await repos.modules.list_by_kb(kb_id, limit=40)
            modules = [m.name for m in all_modules]
            data_modules = [
                m.name for m in all_modules if m.role in {"model", "schema", "data_access"}
            ]

        return {
            "services": services or modules[:12],
            "relations": relations,
            "routes": routes,
            "infra": infra,
            "modules": modules,
            "data_modules": data_modules,
            "entry_points": list(architecture_map.get("entry_points") or [])[:8],
        }

    # ── Drawing ───────────────────────────────────────────────────────────────

    async def _draw(self, spec: DiagramSpec, project, vocab: dict, doc: dict) -> dict | None:
        """
        Draw, check, render — and drop rather than publish something broken.

        Three gates, cheapest first: a structural check that rejects obvious garbage
        without spawning a browser, a grounding check that rejects labels which are not
        real components, and finally the renderer, which is the only true parser we
        have. One repair attempt sits between the gates and the drop.
        """
        allowed = self._allowed_nodes(spec, vocab)
        if not allowed:
            return None

        content = await self._ask(spec, project, vocab, doc, allowed)
        if not content:
            # Never silent: job 8 produced nothing at all and the only trace of it was
            # an absent file.
            await self._emit_log("warning", f"Diagram '{spec.name}' dropped — no output")
            return None

        problem = self._inspect(content, allowed)
        if problem:
            await self._emit_log("info", f"Diagram '{spec.name}' rejected ({problem}) — repairing")
            content = await self._repair(spec, content, problem, allowed)
            problem = self._inspect(content, allowed) if content else "empty after repair"

        if problem:
            await self._emit_log("warning", f"Diagram '{spec.name}' dropped — {problem}")
            return None

        # The renderer is the real Mermaid parser; anything it refuses would have shipped
        # as an error box. A dotted participant id (`neurosurfer.app.server`) passes every
        # structural check and still fails here.
        png = render_png(content)
        if png is None:
            await self._emit_log(
                "info", f"Diagram '{spec.name}' failed to render — repairing"
            )
            content = await self._repair(
                spec, content, "the diagram does not parse as Mermaid", allowed
            )
            if content and not self._inspect(content, allowed):
                png = render_png(content)

        if png is None:
            await self._emit_log("warning", f"Diagram '{spec.name}' dropped — will not render")
            return None

        await self._emit_log("info", f"Rendered '{spec.name}'", bytes=len(png))
        return {
            "key": spec.key,
            "name": spec.name,
            "diagram_type": spec.mermaid_type.split()[0],
            "doc_type": doc.get("doc_type") or "architecture",
            "content": content,
            "png_base64": base64.b64encode(png).decode("ascii"),
        }

    async def _ask(self, spec: DiagramSpec, project, vocab: dict, doc: dict, allowed) -> str:
        messages = DIAGRAM.render(
            mermaid_type=spec.mermaid_type,
            example=example_for(spec.mermaid_type),
            project_name=project.name,
            purpose=spec.purpose,
            allowed_nodes="\n".join(f"  - {n}" for n in allowed),
            relations=self._render_relations(vocab["relations"]),
            facts=json.dumps(
                {"routes": vocab["routes"][:10], "entry_points": vocab["entry_points"]},
                indent=2,
            ),
            doc_excerpt=(doc.get("content_markdown") or "")[:_DOC_EXCERPT_CHARS]
            or "(document is empty)",
        )
        try:
            raw = await self._call_llm(messages, task_type="diagram")
        except JobCancelled:
            raise
        except Exception as exc:
            await self._emit_log("warning", f"Diagram '{spec.name}' failed: {exc}")
            return ""
        return clean_mermaid(raw or "")

    @staticmethod
    def _inspect(content: str, allowed: list[str]) -> str:
        """Structural validity plus label grounding, as one reason string or empty."""
        if not content:
            return "empty response"
        check = validate_mermaid(content)
        if not check.ok:
            return check.reason
        if unknown := ungrounded_labels(content, allowed):
            # Live failure: given a worked example, a small model reproduced the
            # example's *content* — LoginPage, Customer, P1 — instead of its syntax.
            return "invented components not in the codebase: " + ", ".join(unknown[:5])
        return ""

    async def _repair(
        self, spec: DiagramSpec, diagram: str, reason: str, allowed: list[str]
    ) -> str:
        try:
            raw = await self._call_llm(
                DIAGRAM_REPAIR.render(
                    mermaid_type=spec.mermaid_type,
                    example=example_for(spec.mermaid_type),
                    allowed_nodes="\n".join(f"  - {n}" for n in allowed),
                    reason=reason,
                    diagram=diagram,
                ),
                task_type="diagram",
            )
        except JobCancelled:
            raise
        except Exception:
            return diagram
        return clean_mermaid(raw or "")

    @staticmethod
    def _allowed_nodes(spec: DiagramSpec, vocab: dict) -> list[str]:
        """The label vocabulary for this diagram kind — nothing else may be drawn."""
        if spec.key == "request_sequence":
            nodes = ["Client", *vocab["entry_points"], *vocab["services"][:8]]
            nodes += vocab["routes"][:8]
        elif spec.key == "schemas":
            nodes = vocab["data_modules"][:10] or vocab["modules"][:8]
        elif spec.key == "deployment":
            nodes = [*vocab["infra"][:10], *vocab["services"][:6]]
        else:  # components
            nodes = vocab["services"][:12]
        return list(dict.fromkeys(n for n in nodes if n))

    @staticmethod
    def _render_relations(relations: list[dict]) -> str:
        if not relations:
            return "  (none recorded — infer only what the document states)"
        return "\n".join(
            f"  {r['from']} --{r.get('kind', 'uses')}--> {r['to']}" for r in relations[:15]
        )

    @staticmethod
    def _persist(diagrams: list[dict], sandbox) -> None:
        """Source and picture side by side under runs/{job}/outputs/diagrams/."""
        if not sandbox or not diagrams:
            return
        try:
            diagrams_dir = sandbox.outputs / "diagrams"
            diagrams_dir.mkdir(parents=True, exist_ok=True)
            for d in diagrams:
                safe = f"{d['doc_type']}_{d['name']}".lower().replace(" ", "_").replace("/", "-")
                (diagrams_dir / f"{safe}.mmd").write_text(d["content"], encoding="utf-8")
                if d.get("png_base64"):
                    (diagrams_dir / f"{safe}.png").write_bytes(
                        base64.b64decode(d["png_base64"])
                    )
        except OSError:
            pass
