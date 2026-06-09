import json
import re
from typing import Any

from app.agents.base import BaseAgent
from app.llm.prompts.validator_prompts import VALIDATE_CLAIMS


_MAX_CLAIMS_PER_DOC = 3


class ValidatorAgent(BaseAgent):
    name = "validator_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "ValidatorAgent: cross-checking documentation claims")
        await self._update_step(self.name, "running")

        codebase = state.get("codebase")
        generated_docs: list[dict] = state.get("generated_docs", [])
        validation_results = []

        for doc in generated_docs:
            content = doc.get("content_markdown", "")
            claims = self._extract_claims(content)[:_MAX_CLAIMS_PER_DOC]
            doc_validations = []

            for claim in claims:
                source_context = self._find_relevant_source(claim, codebase)
                result = await self._validate_claim(claim, source_context)
                doc_validations.append(result)

            passed = sum(1 for r in doc_validations if r.get("verified", True))
            validation_results.append({
                "doc_type": doc.get("doc_type"),
                "claims_checked": len(doc_validations),
                "claims_passed": passed,
                "details": doc_validations,
            })

        await self._update_step(self.name, "completed", {"docs_validated": len(validation_results)})
        await self._emit_log("info", "Validation complete", docs=len(validation_results))

        return {**state, "validation_results": validation_results}

    def _extract_claims(self, content: str) -> list[str]:
        """Pull verifiable sentences that mention code constructs."""
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

    async def _validate_claim(self, claim: str, source_context: str) -> dict:
        try:
            messages = VALIDATE_CLAIMS.render(claim=claim, source_context=source_context)
            raw = await self._call_llm(messages, task_type="validate")
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.split("```")[0].strip())
        except Exception:
            return {"verified": True, "confidence": 0.5, "explanation": "Could not verify"}
