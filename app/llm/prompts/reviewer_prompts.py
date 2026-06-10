from app.llm.prompts.base import PromptTemplate

REVIEW_DOC = PromptTemplate(
    system=(
        "You are a senior technical documentation reviewer. "
        "Review documentation for accuracy, clarity, completeness, and consistency.\n\n"
        "Return ONLY valid JSON with EXACTLY these 4 fields — no other fields, no markdown fences, no prose:\n"
        '{"score": 8, "issues": ["Missing error handling section"], "suggestions": ["Add code examples"], "approved": true}\n\n'
        "Field rules:\n"
        "- score: integer 0-10\n"
        "- issues: list of strings (empty list [] if none)\n"
        "- suggestions: list of strings (empty list [] if none)\n"
        "- approved: boolean (true if score >= 6 and no blocking issues)"
    ),
    user=(
        "Review this documentation.\n\nTitle: $title\nType: $doc_type\n\n"
        "Content:\n$content\n\n"
        "Return ONLY the JSON object. No explanation before or after."
    ),
)

REVIEW_CORRECTION = PromptTemplate(
    system=(
        "You are a JSON formatter. Return only valid JSON, no prose."
    ),
    user=(
        "The following response is missing the required 'approved' field. "
        "Add it (true if score >= 6, false otherwise) and return the corrected JSON.\n\n"
        "Original response:\n$original_response"
    ),
)
