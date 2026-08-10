"""
Inspect what a question retrieves from a knowledge base.

    python scripts/ask.py 2 "how is the database initialised"
    python scripts/ask.py 2 --file scripts/questions.txt
    python scripts/ask.py 2 "where is data stored" --full

Prints the routing decision, then every piece of evidence with the reason it was
retrieved. **No model is called and no answer is generated** — this is the input an
Ask-the-code agent would receive, exposed so it can be judged before that agent is
worth building.

The scoring column is the point. Run the question set, read the evidence, and record
for each question whether what is needed to answer it is actually present. That
number decides whether the feature is worth writing, and is far more honest than a
demo of the two questions that happen to work.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from codelith.db.session import AsyncSessionLocal  # noqa: E402
from codelith.knowledge.questions import QuestionRouter  # noqa: E402
from codelith.models.knowledge import KnowledgeBase  # noqa: E402

_BODY_PREVIEW = 400


async def _latest_kb(db, project_id: int) -> KnowledgeBase | None:
    return (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == project_id)
            .order_by(KnowledgeBase.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def ask(project_id: int, questions: list[str], full: bool, budget: int) -> int:
    async with AsyncSessionLocal() as db:
        kb = await _latest_kb(db, project_id)
        if kb is None:
            print(f"No knowledge base for project {project_id}. Analyse it first.")
            return 1
        print(f"KB #{kb.id}  commit={(kb.commit_sha or '')[:8]}  status={kb.status}\n")

        router = QuestionRouter(db, kb.id, project_id)
        empty = 0

        for question in questions:
            bundle = await router.gather(question, token_budget=budget)
            print("=" * 78)
            print(f"Q: {question}")
            print(f"   routed: {bundle.plan.describe()}")
            print(f"   found : {bundle.counts or '(nothing)'}")
            if not bundle.items:
                empty += 1
            print()

            for item in bundle.items:
                body = item.body if full else item.body[:_BODY_PREVIEW]
                truncated = "" if full or len(item.body) <= _BODY_PREVIEW else " …"
                print(f"  [{item.kind}] {item.title}")
                print(f"      why: {item.why}")
                for line in (body + truncated).splitlines()[: (200 if full else 6)]:
                    print(f"      {line}")
                print()

        print("=" * 78)
        print(f"{len(questions)} question(s), {empty} with no evidence at all")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect knowledge-base retrieval.")
    parser.add_argument("project_id", type=int)
    parser.add_argument("question", nargs="*", help="the question, unquoted or quoted")
    parser.add_argument("--file", help="a file of questions, one per line")
    parser.add_argument("--full", action="store_true", help="print whole bodies")
    parser.add_argument("--budget", type=int, default=6000, help="token budget")
    args = parser.parse_args()

    questions: list[str] = []
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        questions += [
            line.strip() for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        ]
    if args.question:
        questions.append(" ".join(args.question))
    if not questions:
        parser.error("give a question, or --file")

    return asyncio.run(ask(args.project_id, questions, args.full, args.budget))


if __name__ == "__main__":
    raise SystemExit(main())
