"""
Prompts for Phase 2 (composition).

Every one of these reads from a knowledge base that already exists. None of them
asks the model to go and discover the codebase — that work was done once, during
analysis, and is what makes writing a second document type cheap.
"""

from app.llm.prompts.base import PromptTemplate

SECTION_PLAN = PromptTemplate(
    system=(
        "You are a documentation architect. Using the knowledge base below, produce a "
        "section plan for ONE document type.\n\n"
        "Respond ONLY with valid JSON — no markdown fences, no prose:\n"
        '{"title":str,"sections":[{"name":str,"focus":str,"key_files":[str]}]}\n\n'
        "Rules:\n"
        "  - `title` is the document's real title, naming the project and what the "
        "document is — e.g. 'Acme API Reference'. Never just the document type.\n"
        "  - 4 to 7 sections. Order them the way a reader should meet them.\n"
        "  - `key_files` MUST be paths copied exactly from the module inventory. Never "
        "invent a path. 2-5 files per section; an empty list is better than a guess.\n"
        "  - `focus` is one sentence saying what the section must explain.\n"
        "  - Base the plan on what this codebase actually contains. Do not include a "
        "section the evidence cannot support."
    ),
    user=(
        "Project: $project_name\n"
        "Document type: $doc_type\n"
        "Audience: $audience\n\n"
        "System overview:\n$overview\n\n"
        "Module inventory (path — role — summary):\n$module_inventory\n\n"
        "Known facts:\n$facts"
    ),
)

COMPOSITION_STRATEGY = PromptTemplate(
    system=(
        "You are a documentation strategist. Decide how the requested documents should "
        "be pitched, given what this codebase actually is.\n\n"
        "Respond ONLY with valid JSON — no markdown fences, no prose:\n"
        '{"audiences":[{"doc_type":str,"audience":str,"tone":str}],'
        '"generate_diagrams":bool}\n\n'
        "Set generate_diagrams true only when there are real components or flows worth "
        "drawing — multiple services, a request pipeline, async processing. Set it false "
        "for a small library or a single script."
    ),
    user=(
        "Project: $project_name\n"
        "Requested document types: $doc_types\n\n"
        "System overview:\n$overview\n\n"
        "Architecture:\n$architecture\n\n"
        "Module roles: $roles\n"
        "Known facts: $facts"
    ),
)

SECTION_WRITE = PromptTemplate(
    system=(
        "You are a senior technical writer. Write ONE section of $doc_type "
        "documentation for '$project_name'.\n\n"
        "Everything you need has been retrieved for you and appears below — module "
        "summaries, prior analysis, and verbatim source. Treat it as already read.\n\n"
        "Rules:\n"
        "  - Start with '## $section_name'. Write only this section.\n"
        "  - Ground every statement in the supplied context. Never invent a function, "
        "flag, endpoint or file that does not appear there.\n"
        "  - Reference real paths and symbol names so a reader can verify you.\n"
        "  - Use fenced code blocks for examples, drawn from the source shown.\n"
        "  - Audience: $audience. Tone: $tone.\n"
        "  - Prefer being short and correct over long and padded.\n"
        "  - Do not repeat content from sections already written.\n\n"
        "If — and only if — the context genuinely does not contain what this section "
        "needs, reply with exactly one line and nothing else:\n"
        "NEED_CONTEXT: <a specific search query>\n"
        "Use this sparingly; you get one such request per section."
    ),
    user=(
        "Section: $section_name\n"
        "This section must explain: $focus\n\n"
        "$already_written"
        "Context:\n$context"
    ),
)

__all__ = ["SECTION_PLAN", "COMPOSITION_STRATEGY", "SECTION_WRITE"]
