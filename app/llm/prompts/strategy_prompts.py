from app.llm.prompts.base import PromptTemplate

DOCUMENTATION_STRATEGY = PromptTemplate(
    system=(
        "You are a technical documentation strategist. Given the full architecture and files, "
        "produce a prioritized documentation strategy.\n\n"
        "Respond ONLY with valid JSON — no markdown fences, no prose:\n"
        '{"audiences":[{"doc_type":str,"audience":str,"tone":str}],'
        '"priorities":[str],'
        '"generate_diagrams":bool,'
        '"template_hints":[{"doc_type":str,"sections":[str]}]}\n\n'
        "Set generate_diagrams=true only when the project has meaningful services, flows, or components "
        "worth visualising (multi-service, request pipelines, async flows). "
        "Set false for single-file scripts or trivial projects."
    ),
    user=(
        "Project: $project_name\n"
        "Requested doc types: $doc_types\n\n"
        "Full architecture map:\n$architecture_json\n\n"
        "Key source files:\n$file_listing\n\n"
        "Entry points: $entry_points\n"
        "Patterns: $patterns"
    ),
)
