from app.llm.prompts.base import PromptTemplate

REVIEW_DOC = PromptTemplate(
    system=(
        "You are a senior technical documentation reviewer. "
        "Review documentation for accuracy, clarity, completeness, and consistency. "
        "Return a JSON review report."
    ),
    user=(
        "Review the following documentation.\n\nTitle: $title\nType: $doc_type\n\n"
        "Content:\n$content\n\n"
        'Return JSON: {"score": 0-10, "issues": ["..."], "suggestions": ["..."], "approved": true|false}'
    ),
)
