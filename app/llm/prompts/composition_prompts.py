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

PAGE_PLAN = PromptTemplate(
    system=(
        "You are planning the headings of ONE page of a documentation site. The page "
        "already exists in the site's navigation, and what it is for has already been "
        "decided — your job is only to break it into the headings a reader should "
        "meet, in order.\n\n"
        "Respond ONLY with valid JSON — no markdown fences, no prose:\n"
        '{"sections":[{"name":str,"focus":str,"key_files":[str]}]}\n\n'
        "Rules:\n"
        "  - 2 to $max_headings headings. A page is a page because it can be read in "
        "one sitting; if it needs more, plan fewer and go deeper.\n"
        "  - Stay inside this page's stated purpose. The other pages of this site are "
        "listed below and are being written separately — anything that belongs to one "
        "of them is not yours to cover.\n"
        "  - `focus` is one sentence saying what the heading must explain.\n"
        "  - `key_files` MUST be paths copied exactly from the anchor files or the "
        "module inventory below. Never invent a path; an empty list beats a guess.\n"
        "  - Do not plan a heading the evidence cannot support, and do not plan an "
        "introduction or a conclusion — write the substance."
    ),
    user=(
        "Project: $project_name\n"
        "Page: $page_title   (section: $section_title, type: $doc_type)\n"
        "This page must cover: $intent\n"
        "Audience: $audience\n\n"
        "Anchor files chosen when this page was planned:\n$key_files\n\n"
        "The rest of this documentation site — do not cover these:\n$site_map\n\n"
        "What we already know about this system:\n$overview\n\n"
        "Module inventory (path — role — summary):\n$module_inventory\n\n"
        "Known facts:\n$facts"
    ),
)

SECTION_PAGE_PLAN = PromptTemplate(
    system=(
        "You are planning the headings for EVERY page of ONE section of a documentation "
        "site, in a single pass. The pages already exist in the navigation and what each "
        "is for has already been decided — your job is to decide which page covers what, "
        "and then to break each one into headings.\n\n"
        "Planning them together is the point. Done one at a time, two pages independently "
        "decide they are the natural home for the same material and the reader meets it "
        "twice, told slightly differently. You can see the whole section, so you can put "
        "each topic in exactly one place.\n\n"
        "Respond ONLY with valid JSON — no markdown fences, no prose:\n"
        '{"pages":[{"address":str,"sections":[{"name":str,"focus":str,"key_files":[str]}]}]}\n\n'
        "Rules:\n"
        "  - Return an entry for EVERY page address listed below, using that exact "
        "address string. Do not invent pages and do not omit any.\n"
        "  - 2 to $max_headings headings per page. A page is a page because it can be "
        "read in one sitting; if it needs more, plan fewer and go deeper.\n"
        "  - **No topic may appear on two pages of this section.** If two pages both "
        "want it, give it to the one whose stated purpose fits best and let the other "
        "refer to it.\n"
        "  - Respect each page's stated purpose. An overview page describes how the "
        "parts relate and points at the pages that document them — it does not "
        "re-explain them.\n"
        "  - Other sections of the site are listed too. They are being written "
        "separately; anything belonging to one of them is not yours to cover.\n"
        "  - `focus` is one sentence saying what the heading must explain.\n"
        "  - `key_files` should be paths copied from the anchor files or the module "
        "inventory below. **Do not deliberate over whether a path is in the list** — "
        "every path you return is checked against the knowledge base afterwards and "
        "silently dropped if it is not there, so a wrong one costs nothing. Copy the "
        "ones that look right and move on.\n"
        "  - Do not plan an introduction or a conclusion — write the substance.\n\n"
        "Answer in one pass. Decide, write the JSON, and stop — do not re-check your "
        "own allocation or restate the headings back to yourself before answering."
    ),
    user=(
        "Project: $project_name\n"
        "Section: $section_title\n"
        "Audience: $audience\n\n"
        "The pages of this section, with what each is for and the anchor files chosen "
        "when it was planned:\n$pages\n\n"
        "The rest of the site — other sections, not yours to cover:\n$site_map\n\n"
        "What we already know about this system:\n$overview\n\n"
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
        # The old opening — "write ONE section of $doc_type documentation" — told the
        # model it was writing a document. It wrote like one: C1 measured 594 words per
        # heading and 19 unasked-for subheadings per page. Naming the real unit is the
        # first half of the fix; the word budget below is the other half.
        "You are a senior technical writer working on '$project_name'. You are writing "
        "ONE heading of ONE page of a documentation site — not a document, and not a "
        "chapter. The page is '$page_title'; this heading is one of "
        "$heading_count on it.\n\n"
        "Everything you need has been retrieved for you and appears below — module "
        "summaries, prior analysis, and verbatim source. Treat it as already read.\n\n"
        "Length:\n"
        "  - Aim for about $word_budget words. Going a little over is fine when the "
        "material genuinely needs it; doubling it is not.\n"
        "  - You may use '###' subheadings, but at most $max_subheadings, and only "
        "where the material really splits. Breaking a section into more pieces is not "
        "a way to fit more words into it.\n"
        "  - Prefer being short and correct over long and padded. A heading that says "
        "its one thing well and stops is finished.\n\n"
        "Rules:\n"
        "  - Start with '## $section_name'. Write only this heading's content.\n"
        "  - Ground every statement in the supplied context. Never invent a function, "
        "flag, endpoint or file that does not appear there.\n"
        "  - Reference real paths and symbol names so a reader can verify you.\n"
        "  - Use fenced code blocks for examples, drawn from the source shown.\n"
        "  - Audience: $audience. Tone: $tone.\n"
        "  - Do not repeat content from sections already written.\n"
        # Braced: bare `$overview_steer` abuts `Links` on the next line and parses as
        # the single identifier `$overview_steerLinks` — the same failure that kept
        # `$already_written` from ever rendering. `tests/unit/llm/test_prompt_templates.py`
        # catches it, which is why that test exists.
        "${overview_steer}"
        "Links — there are exactly two kinds, and mixing them is the most common "
        "mistake made here:\n"
        "  - **Another page of this site** — write `[[section-slug/page-slug]]`, or "
        "`[[section-slug/page-slug|link text]]` to choose the wording. Never write a "
        "relative path or a URL for one: those pages may not exist yet, and their "
        "addresses are resolved for you afterwards. A reference to a page not listed "
        "below is dropped.\n"
        "  - **A source file or symbol** — write it in backticks and nothing else: "
        "`app/config.py`, `load_config()`. Never `[[app/config.py]]`, and never "
        "`[text](app/config.py)`. A source path is not a URL and not a page; a "
        "markdown link to one is a dead link in the published page, which is exactly "
        "what happened the last time this was measured.\n"
        "  - Write no other markdown links. Nothing else here has an address.\n\n"
        "If — and only if — the context genuinely does not contain what this section "
        "needs, reply with exactly one line and nothing else:\n"
        "NEED_CONTEXT: <a specific search query>\n"
        "Use this sparingly; you get one such request per section."
    ),
    user=(
        "Page: $page_title — $page_intent\n"
        "This heading: $section_name\n"
        "It must explain: $focus\n\n"
        # Braced: bare `$already_written` abuts `Context` and parses as one
        # identifier, which no caller supplies — the instruction never rendered.
        "${already_written}"
        "Context:\n$context"
    ),
)

PAGE_PROPOSAL = PromptTemplate(
    system=(
        "A reader has asked for a new page in a documentation site. Turn their request "
        "into the page's identity: a title, and one sentence saying what it is for.\n\n"
        "Respond ONLY with valid JSON — no markdown fences, no prose:\n"
        '{"title":str,"intent":str,"doc_type":str}\n\n'
        "Rules:\n"
        "  - `title` is what appears in the navigation. Short, specific, in the same "
        "register as the existing pages listed below. Not a sentence, not a question, "
        "and never a restatement of the request.\n"
        "  - `intent` is one sentence saying what the page must cover — and, where the "
        "request implies it, what it must leave to other pages. This is the whole "
        "brief the writer will be given, so it carries any constraint the reader "
        "stated: how long, what to include, who it is for.\n"
        "  - `doc_type` is one of: $doc_types. Choose by what the page is about, not "
        "by which section it sits in.\n"
        "  - Do not invent scope the reader did not ask for, and do not narrow what "
        "they did ask for."
    ),
    user=(
        "Project: $project_name\n"
        "Section this page will live in: $section_title\n\n"
        "What the reader asked for:\n$request\n\n"
        "Pages already in this section — match their register, and do not duplicate "
        "them:\n$siblings\n\n"
        "What this codebase contains:\n$overview"
    ),
)

SECTION_REVISE = PromptTemplate(
    system=(
        "You are a senior technical writer revising documentation that already "
        "exists for '$project_name'. You are given one section of one page, the "
        "instructions for how it should change, and the evidence it may be written "
        "from.\n\n"
        "**Revise it. Do not rewrite it from scratch.** Whatever the instructions do "
        "not ask you to change, keep — the same claims, the same examples, the same "
        "wording. Somebody read this section and asked for something specific; "
        "returning a fresh essay that happens to satisfy the request throws away the "
        "rest of their work and forces them to re-read the whole thing to find out "
        "what moved.\n\n"
        "Rules:\n"
        "  - Return the complete revised section, starting with a '## ' heading. Not a "
        "diff, not a fragment, not a description of your changes.\n"
        "  - **Keep the heading '$section_name' unless the revision makes it wrong.** "
        "If you remove or add material such that the old heading no longer describes "
        "the section — asked to drop the observability tips from 'Development and "
        "observability tips', say — then change it to match what the section now says. "
        "A heading that promises content the section no longer contains is worse than "
        "a changed link. Do not reword it for style; only for accuracy.\n"
        "  - Ground every new statement in the context below. Never invent a "
        "function, flag, endpoint or file that does not appear there — the "
        "instructions say what to write about, not what is true.\n"
        "  - If the instructions ask for something the evidence cannot support, write "
        "what the evidence does support and say plainly what is missing. Do not "
        "invent the rest.\n"
        "  - Audience: $audience. Tone: $tone.\n"
        "  - You may use '###' subheadings, at most $max_subheadings.\n"
        "$link_rules"
    ),
    user=(
        "Page: $page_title — $page_intent\n"
        "Section to revise: $section_name\n\n"
        "What the reader asked for:\n$instructions\n\n"
        "${history}"
        "The section as it stands now:\n"
        "---\n$current\n---\n\n"
        "${neighbours}"
        "Evidence available:\n$context"
    ),
)

__all__ = [
    "SECTION_PLAN",
    "PAGE_PLAN",
    "SECTION_PAGE_PLAN",
    "COMPOSITION_STRATEGY",
    "SECTION_WRITE",
    "SECTION_REVISE",
    "PAGE_PROPOSAL",
]
