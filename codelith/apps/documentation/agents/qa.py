from __future__ import annotations

import json
import re
from typing import Any

from codelith.agents.base import BaseAgent
from codelith.knowledge.sites import doc_key
from codelith.llm.prompts.qa_prompts import QA_CORRECTION, QA_REVIEW
from codelith.tools.search_tools import semantic_search
from codelith.tracing.artifacts import save_artifact

_CONTENT_LIMIT = 8000
_MAX_CLAIMS_PER_DOC = 4
_EVIDENCE_PER_CLAIM = 3
_DEFAULT_REVIEW = {"score": 7, "approved": True, "issues": [], "suggestions": [], "claim_checks": []}


class QAAgent(BaseAgent):
    """Merged validator + reviewer: one LLM call per doc that reviews quality AND
    verifies claims against evidence retrieved via vector search (no ReAct loop)."""

    name = "qa_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="QAAgent: reviewing and fact-checking documents",
            end_message="QAAgent: complete",
        ) as t:
            await self._emit_log("info", "QAAgent: reviewing and fact-checking documents")
            await self._update_step(self.name, "running")

            project = state["project"]
            generated_docs: list[dict] = (
                state.get("linked_docs") or state.get("generated_docs") or []
            )

            review_results: list[dict] = []
            validation_results: list[dict] = []

            # Deduplicate (state doubling guard). Keyed on the page address in page
            # mode: three pages of type `api` are three documents to fact-check, and
            # keying on doc_type alone silently QA'd one and passed the other two.
            seen: set[str] = set()
            for doc in generated_docs:
                key = doc_key(doc)
                if key in seen:
                    continue
                seen.add(key)
                doc_type = doc.get("doc_type") or ""

                content = doc.get("content_markdown", "")
                claims = self._extract_claims(content)[:_MAX_CLAIMS_PER_DOC]
                claims_block = await self._build_claims_block(claims, project.id)

                review = await self._qa_doc(doc, claims_block)

                claim_checks = review.get("claim_checks") or []
                passed = sum(1 for c in claim_checks if c.get("verified", True))
                review_results.append(
                    {"doc_type": doc_type, "address": doc.get("address"), "review": review}
                )
                validation_results.append({
                    "doc_type": doc_type,
                    "address": doc.get("address"),
                    "claims_checked": len(claim_checks),
                    "claims_passed": passed,
                    "details": claim_checks,
                })
                await self._emit_log(
                    "info", f"QA complete for {key}",
                    score=review.get("score"), approved=review.get("approved"),
                    claims_passed=f"{passed}/{len(claim_checks)}",
                )

            save_artifact(
                "qa.reviews",
                {"reviews": review_results, "validations": validation_results},
            )

            all_approved = all(r["review"].get("approved", False) for r in review_results)

            t.outputs(all_approved=all_approved, docs_reviewed=len(review_results))
            await self._update_step(self.name, "completed", {"all_approved": all_approved})
            return {
                "review_results": review_results,
                "validation_results": validation_results,
                "all_approved": all_approved,
            }

    # ── Evidence retrieval (Python-side, no agent loop) ───────────────────────

    async def _build_claims_block(self, claims: list[str], project_id: int) -> str:
        if not claims:
            return "(no verifiable claims extracted — focus on quality review; claim_checks may be [])"
        blocks: list[str] = []
        for i, claim in enumerate(claims, start=1):
            evidence = await self._search_evidence(claim, project_id)
            blocks.append(f"Claim {i}: {claim}\nEvidence:\n{evidence}")
        return "\n\n".join(blocks)

    async def _search_evidence(self, claim: str, project_id: int) -> str:
        try:
            results = await semantic_search(
                query=claim, project_id=project_id, db=self.db, limit=_EVIDENCE_PER_CLAIM
            )
        except Exception as exc:
            self.log.warning("qa_evidence_search_failed", error=str(exc))
            results = []
        if not results:
            return "  (no matching source code found)"
        lines = []
        for r in results:
            loc = f"{r['path']}:{r.get('start_line', '?')}-{r.get('end_line', '?')}"
            snippet = (r.get("content") or "")[:500]
            lines.append(f"  --- {loc} ---\n{snippet}")
        return "\n".join(lines)

    # ── Review call ────────────────────────────────────────────────────────────

    async def _qa_doc(self, doc: dict, claims_block: str) -> dict:
        messages = QA_REVIEW.render(
            title=doc.get("title", ""),
            doc_type=doc.get("doc_type", ""),
            content=(doc.get("content_markdown") or "")[:_CONTENT_LIMIT],
            claims_block=claims_block,
        )
        review = await self._call_llm_json(messages, task_type="review")

        if review is None:
            return dict(_DEFAULT_REVIEW)

        # If `approved` is missing, do one correction retry
        if "approved" not in review:
            correction = QA_CORRECTION.render(original_response=json.dumps(review))
            corrected = await self._call_llm_json(correction, task_type="review")
            if corrected and "approved" in corrected:
                review = corrected
            else:
                review["approved"] = review.get("score", 0) >= 6

        review.setdefault("score", 7)
        review.setdefault("issues", [])
        review.setdefault("suggestions", [])
        review.setdefault("approved", review.get("score", 0) >= 6)
        review.setdefault("claim_checks", [])
        return review

    # ── Claim extraction (from former validator) ──────────────────────────────

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
