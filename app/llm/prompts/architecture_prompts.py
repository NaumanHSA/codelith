from app.llm.prompts.base import PromptTemplate

ARCHITECTURE_ANALYSIS = PromptTemplate(
    system=(
        "You are a senior software architect. Analyze the provided codebase structure and produce "
        "a structured JSON architecture map. Be precise and grounded in the actual file listing.\n\n"
        "Respond ONLY with valid JSON using this exact schema:\n"
        '{"services":[{"name":str,"type":str,"description":str,"files":[str]}],'
        '"tech_stack":{"language":str,"frameworks":[str],"databases":[str],"infra":[str]},'
        '"patterns":[str],"entry_points":[str],"external_dependencies":[str]}'
    ),
    user=(
        "Project: $project_name\n"
        "Language(s): $languages\n"
        "Total files: $file_count\n\n"
        "File listing:\n$file_listing\n\n"
        "Key symbols:\n$symbols_summary"
    ),
)
