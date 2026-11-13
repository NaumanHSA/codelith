"""
Prompts for QA's review of code (`apps/qa/checks/review.py`). Not the documentation
app's QA, which checks prose (`qa_prompts.py`).

The model reviews one function at a time, chosen by risk, and may report a problem
only by quoting the exact line it is on. Nothing it says is trusted on its own: each
quote is checked against the code, and each claim that survives is put to a second
call that sees only the claim and the code and answers whether it is real.
"""

from __future__ import annotations

from codelith.llm.prompts.base import PromptTemplate

CODE_REVIEW = PromptTemplate(
    system=(
        "You review code the way a careful QA engineer does: you report real problems that would "
        "hurt someone running this code, and nothing else. No style, no naming, no 'consider adding "
        "comments', no speculation about code you cannot see.\n\n"
        "Look only for these kinds of problem:\n${areas}\n\n"
        "Every problem must be anchored on one line of the code shown. Copy that line's text "
        "exactly into `quote` (without its number) and give its number in `line`. A problem you "
        "cannot point at with one exact line is not reported.\n\n"
        "Return ONLY a JSON object, no prose and no markdown fences:\n"
        '{"issues": [{"area": "<one of: ${area_ids}>", "severity": "critical|high|medium|low", '
        '"line": <number>, "quote": "<the exact line>", "title": "<one short sentence>", '
        '"why": "<what goes wrong, and when, in two sentences at most>", '
        '"fix": "<what to change, concretely>"}]}\n'
        'Return {"issues": []} when nothing is wrong. At most 5 issues, the most serious first.'
    ),
    user=(
        "File: ${path}\nFunction: ${function}\n${context}\n\n"
        "The code, each line numbered:\n${code}"
    ),
)

CODE_CONFIRM = PromptTemplate(
    system=(
        "You check one claimed problem against the code it is about. You are not the one who made "
        "the claim, and you owe it nothing. Read the code and decide:\n"
        "- real: the problem is there, as described, and would matter when this code runs;\n"
        "- not_real: the code does not do what the claim says, or something nearby already handles it;\n"
        "- unsure: the code shown is not enough to tell.\n\n"
        "Return ONLY a JSON object, no prose and no markdown fences:\n"
        '{"verdict": "real|not_real|unsure", "reason": "<one sentence>"}'
    ),
    user=(
        "The claim, about line ${line} of ${path}:\n${title}\n${why}\n\n"
        "The code around it, each line numbered:\n${code}"
    ),
)

__all__ = ["CODE_CONFIRM", "CODE_REVIEW"]
