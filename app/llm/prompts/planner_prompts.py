from app.llm.prompts.base import PromptTemplate

DOCUMENTATION_PLAN = PromptTemplate(
    system=(
        "You are a documentation architect. Analyze software projects and produce structured documentation plans. "
        "Return your output as a JSON object."
    ),
    user=(
        "Analyze this project and produce a documentation plan.\n\n"
        "Project Name: $project_name\n"
        "Languages: $languages\n"
        "File Count: $file_count\n"
        "Requested Doc Types: $doc_types\n\n"
        "Return a JSON with:\n"
        '{"documents": [{"type": "...", "title": "...", "priority": 1-5, "estimated_sections": 3}], '
        '"total_estimated_tokens": 10000, "strategy_notes": "..."}'
    ),
)
