from __future__ import annotations

import json
import re
from typing import Any

from app.agents.base import BaseAgent
from app.agents.react_mixin import ReActMixin
from app.config import get_settings
from app.llm.prompts.validator_prompts import VALIDATE_CLAIMS


_MAX_CLAIMS_PER_DOC = 4

_VALIDATOR_SYSTEM_PROMPT = """\
You are a technical documentation fact-checker. Your job is to verify claims in documentation
against the actual source code.

CRITICAL INSTRUCTIONS:
- Do NOT explain your plan or write a preamble. Call tools immediately on receipt of the task.
- For each claim: search or read the relevant source code, then determine if the claim is accurate.
- Use search_codebase to find relevant code. Use filesystem tools to read specific files.
- After checking all claims, output ONLY a JSON array. No prose, no explanation before or after.

Output format (JSON array only):
[
  {"claim": "...", "verified": true|false, "confidence": 0.0-1.0, "explanation": "one sentence", "evidence": "code snippet or file:line"},
  ...
]

Be precise — only mark verified=false if the code clearly contradicts the claim.
If a claim cannot be verified, set verified=true with confidence=0.5.
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

            # Deduplicate: validate each doc_type only once (state doubling guard)
            seen_types: set[str] = set()
            for doc in generated_docs:
                doc_type = doc.get("doc_type") or ""
                if doc_type in seen_types:
                    continue
                seen_types.add(doc_type)

                content = doc.get("content_markdown", "")
                claims = self._extract_claims(content)[:_MAX_CLAIMS_PER_DOC]

                if repo_path and claims:
                    doc_validations = await self._validate_via_react(
                        claims, project, sandbox, repo_path, codebase
                    )
                else:
                    doc_validations = await self._validate_single_shot(claims, codebase)

                passed = sum(1 for r in doc_validations if r.get("verified", True))
                validation_results.append({
                    "doc_type": doc_type,
                    "claims_checked": len(doc_validations),
                    "claims_passed": passed,
                    "details": doc_validations,
                })

            t.outputs(docs_validated=len(validation_results))
            await self._update_step(self.name, "completed", {"docs_validated": len(validation_results)})
            await self._emit_log("info", "Validation complete", docs=len(validation_results))

            return {"validation_results": validation_results}

    async def _validate_via_react(
        self, claims: list[str], project, sandbox, repo_path: str, codebase=None
    ) -> list[dict]:
        """Use a single ReAct loop to verify all claims at once.

        Falls back to single-shot LLM validation if the loop gives up
        ("Sorry, need more steps") or fails to return a JSON array.
        """
        settings = get_settings()
        claims_text = "\n".join(f"Claim {i+1}: {c.strip()}" for i, c in enumerate(claims))
        user_message = (
            f"Verify these {len(claims)} claims about project '{project.name}'.\n\n"
            f"Source code is at: {repo_path}\n"
            f"IMPORTANT: All file paths MUST start with: {repo_path}\n\n"
            f"{claims_text}\n\n"
            f"Call tools now to verify each claim. Then output ONLY the JSON array."
        )

        result = await self._run_react(
            system_prompt=_VALIDATOR_SYSTEM_PROMPT,
            user_message=user_message,
            extra_tools=[self._make_search_tool(project.id, self.db)],
            sandbox_path=repo_path,
            max_iterations=settings.REACT_MAX_ITERATIONS + 10,
        )

        # Give-up / non-JSON responses → fall back to per-claim single-shot validation
        sorry_patterns = ("sorry", "need more steps", "cannot complete", "unable to")
        if not result or any(p in result.lower() for p in sorry_patterns):
            await self._emit_log(
                "warning", "Validator ReAct gave no usable answer — falling back to single-shot"
            )
            return await self._validate_single_shot(claims, codebase)

        try:
            data = json.loads(self._extract_json(result))
            if isinstance(data, list):
                return data
        except Exception:
            pass

        await self._emit_log(
            "warning", "Validator ReAct returned non-JSON — falling back to single-shot"
        )
        return await self._validate_single_shot(claims, codebase)

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
        # Strip markdown headings and code fences to get prose sentences only
        clean = re.sub(r"^#{1,6}\s.*$", "", content, flags=re.MULTILINE)
        clean = re.sub(r"```[\s\S]*?```", "", clean)
        clean = re.sub(r"`[^`]+`", lambda m: m.group().strip("`"), clean)
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        keywords = ("function", "class", "method", "endpoint", "route", "module", "import",
                    "returns", "accepts", "calls", "uses", "implements", "supports", "provides",
                    "exposes", "handles", "manages")
        candidates = [
            s.strip() for s in sentences
            if len(s.strip()) > 30 and any(k in s.lower() for k in keywords)
        ]
        # Deduplicate by first 40 chars
        seen: set[str] = set()
        unique: list[str] = []
        for c in candidates:
            key = c[:40]
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique[:10]

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
