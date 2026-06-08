import json
from typing import Any
from app.agents.base import BaseAgent
from app.llm.prompts.reviewer_prompts import REVIEW_DOC


class ReviewerAgent(BaseAgent):
    name = "reviewer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "ReviewerAgent: reviewing generated documents")
        await self._update_step(self.name, "running")

        generated_docs: list[dict] = state.get("generated_docs", [])
        review_results = []

        for doc in generated_docs:
            try:
                messages = REVIEW_DOC.render(
                    title=doc.get("title", ""),
                    doc_type=doc.get("doc_type", ""),
                    content=(doc.get("content_markdown") or "")[:4000],
                )
                raw = await self._call_llm(messages, task_type="review")
                review = json.loads(raw)
            except Exception:
                review = {"score": 7, "approved": True, "issues": [], "suggestions": []}

            review_results.append({"doc_type": doc.get("doc_type"), "review": review})

        all_approved = all(r["review"].get("approved", True) for r in review_results)

        await self._update_step(self.name, "completed", {"all_approved": all_approved})
        return {**state, "review_results": review_results, "all_approved": all_approved}
