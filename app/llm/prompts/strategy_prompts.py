from app.llm.prompts.base import PromptTemplate

DOCUMENTATION_STRATEGY = PromptTemplate(
    system=(
        "You are a technical documentation strategist. Given the architecture and requested doc types, "
        "produce a prioritized documentation strategy.\n\n"
        "Respond ONLY with valid JSON:\n"
        '{"audiences":[{"doc_type":str,"audience":str,"tone":str}],'
        '"priorities":[str],'
        '"template_hints":[{"doc_type":str,"sections":[str]}]}'
    ),
    user=(
        "Project: $project_name\n"
        "Requested doc types: $doc_types\n\n"
        "Architecture summary:\n$architecture_summary"
    ),
)
