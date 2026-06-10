from typing import Any
from app.agents.base import BaseAgent
from app.llm.prompts.reviewer_prompts import REVIEW_CORRECTION, REVIEW_DOC

_CONTENT_LIMIT = 8000
_DEFAULT_REVIEW = {"score": 7, "approved": True, "issues": [], "suggestions": []}


class ReviewerAgent(BaseAgent):
    name = "reviewer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="ReviewerAgent: reviewing generated documents",
            end_message="ReviewerAgent: complete",
        ) as t:
            await self._emit_log("info", "ReviewerAgent: reviewing generated documents")
            await self._update_step(self.name, "running")

            generated_docs: list[dict] = state.get("generated_docs", [])
            review_results = []

            # Deduplicate: review each doc_type only once (state doubling guard)
            seen_types: set[str] = set()
            for doc in generated_docs:
                doc_type = doc.get("doc_type") or ""
                if doc_type in seen_types:
                    continue
                seen_types.add(doc_type)

                review = await self._review_doc(doc)
                review_results.append({"doc_type": doc_type, "review": review})

            all_approved = all(r["review"].get("approved", False) for r in review_results)

            t.outputs(all_approved=all_approved, docs_reviewed=len(review_results))
            await self._update_step(self.name, "completed", {"all_approved": all_approved})
            return {"review_results": review_results, "all_approved": all_approved}

    async def _review_doc(self, doc: dict) -> dict:
        messages = REVIEW_DOC.render(
            title=doc.get("title", ""),
            doc_type=doc.get("doc_type", ""),
            content=(doc.get("content_markdown") or "")[:_CONTENT_LIMIT],
        )
        review = await self._call_llm_json(messages, task_type="review")

        if review is None:
            return _DEFAULT_REVIEW

        # If `approved` is missing, do one correction retry
        if "approved" not in review:
            import json
            original_text = json.dumps(review)
            correction_messages = REVIEW_CORRECTION.render(original_response=original_text)
            corrected = await self._call_llm_json(correction_messages, task_type="review")
            if corrected and "approved" in corrected:
                review = corrected
            else:
                # Derive approved from score as fallback
                review["approved"] = review.get("score", 0) >= 6

        # Ensure all required fields are present
        review.setdefault("score", 7)
        review.setdefault("issues", [])
        review.setdefault("suggestions", [])
        review.setdefault("approved", review.get("score", 0) >= 6)

        return review
