from codelith.llm.prompts.base import PromptTemplate

ARCHITECTURE_DOC = PromptTemplate(
    system=(
        "You are a senior technical writer specializing in software architecture documentation. "
        "Write clear, accurate, and well-structured documentation in Markdown. "
        "Use headings, bullet points, and code blocks where appropriate. "
        "Only state what you can confirm from the provided source context."
    ),
    user=(
        "Generate a comprehensive Architecture Documentation for the following project.\n\n"
        "Project Name: $project_name\n\n"
        "Repository Structure:\n$repo_structure\n\n"
        "Detected Languages: $languages\n\n"
        "Key Files & Symbols:\n$symbols_summary\n\n"
        "Write an Architecture Documentation covering: overview, component breakdown, "
        "data flow, technology stack, and deployment considerations."
    ),
)

MODULE_DOC = PromptTemplate(
    system=(
        "You are a senior technical writer. Write accurate module documentation in Markdown. "
        "Document all public classes and functions. Include parameters, return types, and purpose."
    ),
    user=(
        "Generate module documentation for the following source file.\n\n"
        "File: $file_path\nLanguage: $language\n\n"
        "Source Code:\n```$language\n$source_code\n```\n\n"
        "Write documentation covering: module purpose, classes, functions, usage examples."
    ),
)

API_DOC = PromptTemplate(
    system=(
        "You are a technical writer specializing in API documentation. "
        "Write clear API reference documentation in Markdown."
    ),
    user=(
        "Generate API documentation for the following endpoints.\n\n"
        "Project: $project_name\n\nEndpoints:\n$endpoints_summary\n\n"
        "For each endpoint document: method, path, description, request body, response schema, example."
    ),
)
