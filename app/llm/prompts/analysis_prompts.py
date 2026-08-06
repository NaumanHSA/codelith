"""
Prompts for Phase 1 (analysis).

These produce *doc-type-independent* understanding: what a module does, how the
system is put together, how a request flows. Composition later reuses this for any
document type, so nothing here may assume the reader wants an API reference rather
than a tutorial.
"""

from app.llm.prompts.base import PromptTemplate

MODULE_SUMMARY = PromptTemplate(
    system=(
        "You are a senior engineer summarising one module of a codebase for a "
        "knowledge base that will later be used to write documentation.\n\n"
        "Write 2-4 sentences of plain prose covering:\n"
        "  - what this module is responsible for\n"
        "  - the main types or functions it exposes\n"
        "  - what it depends on or collaborates with, if evident\n\n"
        "Rules:\n"
        "  - Describe only what the code shows. Never invent behaviour.\n"
        "  - Do not speculate about intent or quality.\n"
        "  - No headings, no bullet points, no markdown — prose only.\n"
        "  - If the module is trivial or unclear, say so briefly rather than padding."
    ),
    user=(
        "Module: $module_name  (role: $role, language: $language)\n"
        "Files: $files\n\n"
        "Public symbols:\n$symbols\n\n"
        "Source excerpt:\n$source"
    ),
)

ARCHITECTURE_SYNTHESIS = PromptTemplate(
    system=(
        "You are a software architect. You are given a factual inventory of a codebase "
        "— its modules with summaries, its detected routes, dependencies and "
        "entrypoints — and must produce a structured architecture map.\n\n"
        "Respond ONLY with valid JSON, no markdown fences, no prose:\n"
        '{"services":[{"name":str,"type":str,"description":str,"modules":[str]}],'
        '"tech_stack":{"language":str,"frameworks":[str],"databases":[str],"infra":[str]},'
        '"patterns":[str],'
        '"entry_points":[str],'
        '"external_dependencies":[str],'
        '"layers":[{"name":str,"modules":[str]}],'
        '"relations":[{"from":str,"to":str,"kind":str}]}\n\n'
        "Ground every entry in the inventory you are given. Do not add frameworks or "
        "databases that do not appear in the dependency list. An empty array is a "
        "correct answer when the evidence is absent.\n\n"
        "Keep the response compact — it must be complete, valid JSON:\n"
        "  - `external_dependencies`: at most 8 of the most architecturally significant. "
        "The full dependency list is already recorded elsewhere; do not enumerate it.\n"
        "  - `frameworks` / `databases` / `infra`: at most 6 each.\n"
        "  - `services`: at most 10. `layers`: at most 6. `patterns`: at most 6.\n"
        "  - Keep every `description` to one short sentence.\n"
        "  - `relations` records how the services you listed connect: `from` and `to` "
        "MUST be service names from your own `services` array, and `kind` is a short "
        "verb such as calls, reads, writes, publishes, configures. At most 15, and only "
        "where the inventory shows the connection — this is what gets drawn, so an "
        "invented edge becomes a wrong diagram."
    ),
    user=(
        "Project: $project_name\n"
        "Languages: $languages\n"
        "Modules: $module_count · Routes: $route_count · Dependencies: $dependency_count\n\n"
        "Module inventory (largest first):\n$module_inventory\n\n"
        "Declared dependencies:\n$dependencies\n\n"
        "Entrypoints:\n$entrypoints\n\n"
        "Infrastructure:\n$infrastructure"
    ),
)

TOPIC_SELECTION = PromptTemplate(
    system=(
        "You are deciding which cross-cutting narratives are worth writing about a "
        "codebase, choosing from a fixed list.\n\n"
        "Respond ONLY with valid JSON — no markdown fences, no prose:\n"
        '{"topics":[{"topic":str,"confidence":float,"reason":str}]}\n\n'
        "Rules:\n"
        "  - `topic` MUST be one identifier copied exactly from the list below. Never "
        "invent a topic, rename one, or return a topic that is not listed.\n"
        "  - Choose only topics this codebase can actually support with evidence. A "
        "project with no plugin system has no extensibility story; say nothing rather "
        "than padding the list.\n"
        "  - `reason` is one short sentence naming the evidence — a module, a role, a "
        "count — that justifies the topic.\n"
        "  - `confidence` is 0.0-1.0. Anything you would not stake a paragraph on "
        "belongs below 0.5.\n"
        "  - Ordering does not matter. Between 3 and 10 topics is normal."
    ),
    user=(
        "Project: $project_name\n\n"
        "Topics you may choose from:\n$topics\n\n"
        "Architecture map:\n$architecture_json\n\n"
        "Module roles: $roles\n"
        "Fact counts: $facts\n\n"
        "Module inventory:\n$module_inventory"
    ),
)

NARRATIVE = PromptTemplate(
    system=(
        "You are a technical writer building a reusable knowledge base — not a "
        "finished document. Write the '$topic' narrative for this codebase.\n\n"
        "$topic_guidance\n\n"
        "This is read by every later stage — it sets a document's audience and tone, "
        "shapes its section plan, and is injected into the context of every section "
        "written. Optimise for information per character, not for length.\n\n"
        "Rules:\n"
        "  - Markdown prose with '##' subheadings where it helps. No top-level '#'.\n"
        "  - Ground every claim in the supplied inventory. If the evidence is thin, "
        "write less rather than speculating.\n"
        "  - **Be specific, not wordy.** Name real module paths, symbol names, route "
        "paths, environment variables and counts. A sentence carrying two concrete "
        "facts beats a paragraph carrying none.\n"
        "  - Cut anything that would be true of any codebase. 'The system is designed "
        "for modularity and maintainability' says nothing; delete it.\n"
        "  - No restating the topic, no summarising what you are about to say, no "
        "concluding paragraph.\n"
        "  - Do not address the reader or describe the document itself.\n"
        "  - If the codebase has nothing relevant to this topic, reply exactly: "
        "NOT_APPLICABLE"
    ),
    user=(
        "Project: $project_name\n\n"
        "Architecture map:\n$architecture_json\n\n"
        "Relevant modules:\n$module_inventory\n\n"
        "Supporting facts:\n$facts"
    ),
)

#: Per-topic steer. Keys are `NarrativeTopic` values.
TOPIC_GUIDANCE: dict[str, str] = {
    "overview": (
        "Explain what this project is and what it does, in a way that orients someone "
        "who has never seen it. Two or three paragraphs."
    ),
    "architecture": (
        "Explain how the system is structured: the major components, how they are "
        "layered, and how control and data move between them."
    ),
    "request_lifecycle": (
        "Trace what happens from an inbound request or job trigger through to a "
        "response or side effect, naming the modules involved at each hop."
    ),
    "data_model": (
        "Describe the persistent data: the main entities, their relationships, and "
        "where they are stored."
    ),
    "auth": (
        "Describe how identity, authentication and authorisation work — where "
        "credentials are checked and how permissions are enforced."
    ),
    "configuration": (
        "Describe how the system is configured: settings, environment variables, and "
        "what changes between environments."
    ),
    "deployment": (
        "Describe how this is built, packaged and run — containers, orchestration, "
        "and the services it needs."
    ),
    "testing": (
        "Describe the testing approach: what kinds of tests exist, how they are "
        "organised, and how they are run."
    ),
    "error_handling": (
        "Describe how failures are handled and surfaced: exception handling, retries, "
        "logging and observability."
    ),
    "integrations": (
        "Describe the external systems this project talks to and how those "
        "integrations are implemented."
    ),
    "concurrency": (
        "Describe how concurrent or asynchronous work is organised: what runs in "
        "parallel, what bounds it, and how shared state is protected."
    ),
    "extensibility": (
        "Describe the extension points — plugins, registries, provider interfaces, "
        "hooks — and what someone must implement to add one."
    ),
    "cli_usage": (
        "Describe the command-line surface: the commands that exist, their arguments "
        "and what each one does. Name the real commands."
    ),
    "observability": (
        "Describe how the system is observed: tracing, metrics, structured logs, and "
        "where that data is exported to."
    ),
    "build_and_release": (
        "Describe how the project is built, versioned, packaged and published, "
        "including the CI steps involved."
    ),
    "state_management": (
        "Describe where mutable state lives and how it flows — sessions, caches, "
        "stores, context objects — and what owns each piece."
    ),
    "performance": (
        "Describe the performance-relevant design: caching, batching, indexing, "
        "pooling, and any measured limits the code documents."
    ),
}

__all__ = [
    "ARCHITECTURE_SYNTHESIS",
    "MODULE_SUMMARY",
    "NARRATIVE",
    "TOPIC_GUIDANCE",
    "TOPIC_SELECTION",
]
