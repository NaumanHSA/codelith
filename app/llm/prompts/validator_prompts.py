from app.llm.prompts.base import PromptTemplate

VALIDATE_CLAIMS = PromptTemplate(
    system=(
        "You are a fact-checker for technical documentation. "
        "Given source code and a documentation claim, verify whether the claim is accurate. "
        "Return a JSON verification result."
    ),
    user=(
        "Verify this documentation claim against the source code.\n\n"
        "Claim: $claim\n\nSource Code Context:\n```\n$source_context\n```\n\n"
        'Return JSON: {"verified": true|false, "confidence": 0.0-1.0, "explanation": "..."}'
    ),
)
