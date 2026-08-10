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

from codelith.agents.base import BaseAgent
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.config import get_settings
from codelith.core.cancellation import JobCancelled
from codelith.knowledge.constants import EntityKind
from codelith.knowledge.sites import doc_key
from codelith.llm.prompts.diagram_prompts import DIAGRAM, DIAGRAM_REPAIR, example_for
from codelith.tools.mermaid import clean_mermaid, ungrounded_labels, validate_mermaid
from codelith.tools.mermaid_render import render_png, rendering_available
from codelith.tracing.artifacts import save_text_artifact


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

            # Deterministic first, and on by default. These are built from the code
            # graph and the extracted entities by `app/knowledge/diagrams.py` — no
            # model writes syntax, so they are valid by construction and grounded by
            # construction, which is exactly what the model-written ones were not.
            settings = get_settings()
            graph_diagrams: list[dict] = []
            if settings.DIAGRAMS_FROM_GRAPH:
                graph_diagrams = await self._from_graph(state)

            if not get_settings().DIAGRAMS_ENABLED:
                await self._emit_log(
                    "info",
                    "DiagramAgent: model-written diagrams disabled (DIAGRAMS_ENABLED); "
                    f"{len(graph_diagrams)} graph-derived diagram(s) kept",
                )
                self._persist(graph_diagrams, state.get("sandbox"))
                t.outputs(diagrams=len(graph_diagrams), llm_disabled=True)
                await self._update_step(
                    self.name, "completed",
                    {"diagrams": len(graph_diagrams), "llm_disabled": True},
                )
                return {"diagrams": graph_diagrams}

            strategy: dict = state.get("strategy") or {}
            if not strategy.get("generate_diagrams", True):
                await self._emit_log("info", "DiagramAgent: model diagrams skipped (strategy)")
                self._persist(graph_diagrams, state.get("sandbox"))
                t.outputs(diagrams=len(graph_diagrams), skipped=True)
                await self._update_step(
                    self.name, "completed", {"diagrams": len(graph_diagrams), "skipped": True}
                )
                return {"diagrams": graph_diagrams}

            project = state["project"]
            architecture_map: dict = state.get("architecture_map") or {}
            # Linked copy when the linker ran: a diagram excerpt should show the
            # page as it will be read, not with unresolved [[refs]] in it.
            generated_docs: list[dict] = (
                state.get("linked_docs") or state.get("generated_docs") or []
            )
            sandbox = state.get("sandbox")

            vocabulary = await self._vocabulary(state, architecture_map)

            diagrams: list[dict] = list(graph_diagrams)
            for doc in generated_docs:
                doc_type = doc.get("doc_type") or "architecture"
                specs = self._specs_for(doc_type, vocabulary)
                if not specs:
                    await self._emit_log(
                        "info",
                        f"No diagram warranted for {doc_key(doc) or doc_type} — "
                        "evidence too thin",
                    )
                    continue
                for spec in specs:
                    drawn = await self._draw(spec, project, vocabulary, doc)
                    if drawn:
                        diagrams.append(drawn)

            self._persist(diagrams, sandbox)

            for d in diagrams:
                save_text_artifact(f"diagram.{d['doc_key']}.{d['name']}", d["content"], ext="mmd")

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

        if not rendering_available():
            # Rendering is off, or mmdc is not installed. The diagram is fine — it just
            # cannot be turned into a picture here, so publish the source and let the
            # formatter fall back. Treating this as a failure dropped every diagram.
            await self._emit_log(
                "info", f"Diagram '{spec.name}' kept as source — PNG rendering unavailable"
            )
            return {
                "key": spec.key,
                "name": spec.name,
                "diagram_type": spec.mermaid_type.split()[0],
                "doc_type": doc.get("doc_type") or "architecture",
                "doc_key": doc_key(doc) or "architecture",
                "content": content,
                "png_base64": None,
            }

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
            "doc_key": doc_key(doc) or "architecture",
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

    async def _from_graph(self, state: dict[str, Any]) -> list[dict]:
        """
        Diagrams the knowledge base can draw without asking anything.

        The entire reason diagrams were switched off was that a model wrote the
        syntax and got it wrong. These are built by `app/knowledge/diagrams.py` from
        the import graph and the extracted entities — every box corresponds to a file
        or a fact, and the D2 comes out of a builder, so neither an invented node nor
        a syntax error is reachable.

        Attached to the first document of the run rather than to each: they describe
        the system, not a page, and repeating them under every heading is noise.
        """
        from codelith.knowledge.diagrams import module_map, system_context
        from codelith.tools.d2_render import render_svg

        kb_id = state.get("kb_id")
        docs = state.get("linked_docs") or state.get("generated_docs") or []
        if not kb_id or not docs:
            return []

        project = state["project"]
        repos = KnowledgeRepositories.for_session(self.db)
        modules = await repos.modules.list_by_kb(kb_id)

        # Only the kinds the context diagram draws. There is no "every entity" query,
        # and fetching one would pull hundreds of dependencies to use three of them.
        entities: list[dict] = []
        for kind in (EntityKind.DATASTORE, EntityKind.EXTERNAL_API, EntityKind.ENTRYPOINT):
            entities += [
                {"kind": e.kind, "name": e.name, "data_json": e.data_json}
                for e in await repos.entities.list_by_kind(kb_id, kind, limit=20)
            ]

        sources: list[tuple[str, str, str | None]] = [
            ("system_context", "System Context", system_context(entities, project.name)),
        ]

        files, imports = await self._graph_edges(project.id, kb_id)
        if files:
            roles = {m.path: m.role for m in modules}
            sources.append(("module_map", "Module Dependencies", module_map(files, imports, roles)))

        target = doc_key(docs[0]) or ""
        drawn: list[dict] = []
        for key, name, source in sources:
            if not source:
                continue
            svg = render_svg(source)
            drawn.append({
                "key": key,
                "name": name,
                "doc_key": target,
                "doc_type": docs[0].get("doc_type") or "architecture",
                "content": source,
                "language": "d2",
                "grounded": True,
                **({"svg_base64": base64.b64encode(svg).decode()} if svg else {}),
            })
            await self._emit_log(
                "info",
                f"Drew {name} from the knowledge base"
                + ("" if svg else " (source only — d2 not installed)"),
            )
        return drawn

    async def _graph_edges(self, project_id: int, kb_id: int) -> tuple[list[dict], list[dict]]:
        """Files and import edges from Neo4j. Empty when it is unreachable."""
        from codelith.memory.graph_store import GraphStore

        try:
            async with GraphStore() as graph:
                files = await graph.query(
                    "MATCH (f:File {project_id: $project_id, kb_id: $kb_id}) "
                    "RETURN f.path AS path, f.module_key AS module_key",
                    project_id=project_id, kb_id=kb_id,
                )
                imports = await graph.query(
                    "MATCH (a:File {project_id: $project_id, kb_id: $kb_id})-[:IMPORTS]->(b:File) "
                    "RETURN a.path AS src, b.path AS dst",
                    project_id=project_id, kb_id=kb_id,
                )
            return files, imports
        except Exception as exc:  # pragma: no cover - Neo4j optional
            await self._emit_log("info", f"No code graph available for diagrams: {exc}")
            return [], []

    @staticmethod
    def _persist(diagrams: list[dict], sandbox) -> None:
        """Source and picture side by side under runs/{job}/outputs/diagrams/."""
        if not sandbox or not diagrams:
            return
        try:
            diagrams_dir = sandbox.outputs / "diagrams"
            diagrams_dir.mkdir(parents=True, exist_ok=True)
            for d in diagrams:
                safe = f"{d['doc_key']}_{d['name']}".lower().replace(" ", "_").replace("/", "-")
                (diagrams_dir / f"{safe}.mmd").write_text(d["content"], encoding="utf-8")
                if d.get("png_base64"):
                    (diagrams_dir / f"{safe}.png").write_bytes(
                        base64.b64decode(d["png_base64"])
                    )
        except OSError:
            pass
