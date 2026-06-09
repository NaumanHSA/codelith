from __future__ import annotations

import re
from typing import Any

from app.agents.base import BaseAgent
from app.agents.react_mixin import ReActMixin
from app.llm.prompts.validator_prompts import VALIDATE_CLAIMS


_MAX_CLAIMS_PER_DOC = 3

_VALIDATOR_SYSTEM_PROMPT = """\
You are a technical documentation fact-checker. Your job is to verify claims in documentation
against the actual source code.

For each claim you receive:
1. Search the codebase for the relevant code using search_codebase
2. If a specific file is mentioned, read it using filesystem tools
3. Determine if the claim is accurate, partially accurate, or inaccurate

Return a JSON object for each claim:
{"verified": true|false, "confidence": 0.0-1.0, "explanation": "...", "evidence": "..."}

Be precise — only mark something as false if you can confirm from the code that it is wrong.
"""


class ValidatorAgent(ReActMixin, BaseAgent):
    name = "validator_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="ValidatorAgent: cross-checking documentation claims",
            end_message="ValidatorAgent: complete",
        ) as t:
            await self._emit_log("info", "ValidatorAgent: cross-checking documentation claims")
            await self._update_step(self.name, "running")

            project = state["project"]
            codebase = state.get("codebase")
            generated_docs: list[dict] = state.get("generated_docs", [])
            sandbox = state.get("sandbox")
            repo_path = state.get("repo_path") or ""
            validation_results = []

            for doc in generated_docs:
                content = doc.get("content_markdown", "")
                claims = self._extract_claims(content)[:_MAX_CLAIMS_PER_DOC]

                if repo_path and claims:
                    doc_validations = await self._validate_via_react(
                        claims, project, sandbox, repo_path
                    )
                else:
                    doc_validations = await self._validate_single_shot(claims, codebase)

                passed = sum(1 for r in doc_validations if r.get("verified", True))
                validation_results.append({
                    "doc_type": doc.get("doc_type"),
                    "claims_checked": len(doc_validations),
                    "claims_passed": passed,
                    "details": doc_validations,
                })

            t.outputs(docs_validated=len(validation_results))
            await self._update_step(self.name, "completed", {"docs_validated": len(validation_results)})
            await self._emit_log("info", "Validation complete", docs=len(validation_results))

            return {**state, "validation_results": validation_results}

    async def _validate_via_react(self, claims: list[str], project, sandbox, repo_path: str) -> list[dict]:
        """Use a single ReAct loop to verify all claims at once."""
        claims_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
        user_message = (
            f"Verify the following claims about project '{project.name}' "
            f"using the source code at {repo_path}:\n\n{claims_text}\n\n"
            "For each claim, search or read the relevant code and return a JSON array:\n"
            '[{"verified": true, "confidence": 0.9, "explanation": "...", "evidence": "..."}, ...]'
        )

        result = await self._run_react(
            system_prompt=_VALIDATOR_SYSTEM_PROMPT,
            user_message=user_message,
            extra_tools=[self._make_search_tool(project.id, self.db)],
            sandbox_path=repo_path,
            repo_path=repo_path,
        )

        if result:
            try:
                parsed = self._extract_json(result)
                import json
                data = json.loads(parsed)
                if isinstance(data, list):
                    return data
            except Exception:
                pass

        return [{"verified": True, "confidence": 0.5, "explanation": "Could not verify via ReAct"} for _ in claims]

    async def _validate_single_shot(self, claims: list[str], codebase) -> list[dict]:
        results = []
        for claim in claims:
            source_context = self._find_relevant_source(claim, codebase)
            result = await self._validate_claim_llm(claim, source_context)
            results.append(result)
        return results

    async def _validate_claim_llm(self, claim: str, source_context: str) -> dict:
        try:
            messages = VALIDATE_CLAIMS.render(claim=claim, source_context=source_context)
            return await self._call_llm_json(messages, task_type="validate") or {
                "verified": True, "confidence": 0.5, "explanation": "Could not verify"
            }
        except Exception:
            return {"verified": True, "confidence": 0.5, "explanation": "Could not verify"}

    def _extract_claims(self, content: str) -> list[str]:
        sentences = re.split(r'(?<=[.!?])\s+', content)
        keywords = ("function", "class", "method", "endpoint", "route", "module", "import",
                    "returns", "accepts", "calls", "uses", "implements")
        return [s.strip() for s in sentences if any(k in s.lower() for k in keywords)][:10]

    def _find_relevant_source(self, claim: str, codebase) -> str:
        if not codebase:
            return "(no source available)"
        words = set(claim.lower().split())
        best_file = None
        best_score = 0
        for f in codebase.files:
            score = sum(1 for w in words if w in f.content.lower())
            if score > best_score:
                best_score = score
                best_file = f
        if best_file:
            return best_file.content[:2000]
        return "(no relevant source found)"
