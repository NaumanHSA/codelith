from app.llm.prompts.base import PromptTemplate

DOCUMENTATION_PLAN = PromptTemplate(
    system=(
        "You are a documentation architect. You receive a fully-analyzed project and produce a "
        "precise, file-aware documentation plan.\n\n"
        "Return ONLY valid JSON — no markdown fences, no prose:\n"
        '{"documents": [{'
        '"type": str, '
        '"title": str, '
        '"sections": [{"name": str, "focus": str, "key_files": [str]}]'
        "}]}"
    ),
    user=(
        "Project: $project_name\n"
        "Languages: $languages   File count: $file_count\n"
        "Requested doc types: $doc_types\n\n"
        "Architecture map:\n$architecture_json\n\n"
        "Key files:\n$file_listing\n\n"
        "For each doc type produce 4–7 sections. "
        "For each section name 2–4 key_files from the file listing above that are most relevant to that section. "
        "focus must be one precise sentence describing what to write in that section."
    ),
)
