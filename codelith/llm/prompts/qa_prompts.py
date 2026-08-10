from codelith.llm.prompts.base import PromptTemplate

QA_REVIEW = PromptTemplate(
    system=(
        "You are a senior documentation QA engineer. In ONE pass you both review the "
        "document's quality AND verify its factual claims against the provided source "
        "code evidence.\n\n"
        "Return ONLY valid JSON with EXACTLY these 5 fields — no other fields, no markdown "
        "fences, no prose:\n"
        '{"score": 8, "issues": ["..."], "suggestions": ["..."], "approved": true, '
        '"claim_checks": [{"claim": "...", "verified": true, "confidence": 0.9, "evidence": "file.py:12"}]}\n\n'
        "Field rules:\n"
        "- score: integer 0-10 (overall doc quality)\n"
        "- issues: list of strings (empty list [] if none)\n"
        "- suggestions: list of strings (empty list [] if none)\n"
        "- approved: boolean (true if score >= 6 and no blocking factual errors)\n"
        "- claim_checks: one entry per claim, in the same order as given. "
        "verified=false ONLY when the evidence clearly contradicts the claim; "
        "if the evidence is inconclusive use verified=true with confidence=0.5."
    ),
    user=(
        "Review this documentation and verify the claims below.\n\n"
        "Title: $title\nType: $doc_type\n\n"
        "Document content:\n$content\n\n"
        "Claims to verify (with source-code evidence retrieved for each):\n$claims_block\n\n"
        "Return ONLY the JSON object. No explanation before or after."
    ),
)

QA_CORRECTION = PromptTemplate(
    system=("You are a JSON formatter. Return only valid JSON, no prose."),
    user=(
        "The following response is missing the required 'approved' field. "
        "Add it (true if score >= 6, false otherwise) and return the corrected JSON.\n\n"
        "Original response:\n$original_response"
    ),
)
