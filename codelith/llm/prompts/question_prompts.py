"""
Routing a question, by model rather than by phrase table.

The table-driven router could not survive a codebase it had never seen. "which
modules would I need to touch if I refactored the executor" matches no entry in any
list of phrases, and no amount of tending the list fixes that class of problem — the
inputs are unbounded in both directions, the code *and* the phrasing.

Two things make this safe to hand to a model:

* **It is told what this knowledge base actually contains** — the entity kinds that
  were populated, the narrative topics that exist, the modules that were found. It is
  choosing from a real menu, not guessing at a schema.
* **Nothing it returns is trusted.** Every field is intersected with what exists
  before it is used, so a hallucinated symbol or an invented topic costs one dropped
  list entry rather than a traversal after something imaginary.

The `search_queries` field is the part a phrase table could never produce. "how do I
run this locally" is a poor embedding query; "uvicorn entrypoint, docker compose
services, Makefile dev target" is a good one. Rewriting the question into the
vocabulary the *code* uses is most of what makes retrieval work.

`JUDGE_SCOPE` runs before all of that and answers a question the router cannot: not
*which* store, but whether any of them should be read. Same two safeguards — it is
shown what this repository is about in the words analysis chose, and nothing it
returns is trusted beyond three known verdicts. See `codelith/knowledge/scope.py`.
"""

from __future__ import annotations

from codelith.llm.prompts.base import PromptTemplate

ROUTE_QUESTION = PromptTemplate(
    system=(
        "You route questions about a codebase to the right lookups. You do not "
        "answer the question — something else does that, using what you select.\n\n"
        "Return ONLY a JSON object, no prose and no markdown fences:\n"
        "{\n"
        '  "intents": ["semantic", "entities", "narrative", "graph"],\n'
        '  "entity_kinds": ["datastore"],\n'
        '  "narrative_topics": ["data_model"],\n'
        '  "symbols": ["SessionFactory", "create_async_engine"],\n'
        '  "paths": ["app/db/session.py"],\n'
        '  "search_queries": ["async engine creation", "connection pool settings"],\n'
        '  "reasoning": "one short sentence"\n'
        "}\n\n"
        "Rules:\n"
        "  - `intents` decides which stores are consulted:\n"
        "      semantic  — always include this. Vector search over the source.\n"
        "      entities  — the knowledge base holds this as a structured fact\n"
        "                  (datastores, routes, scheduled tasks, env vars...).\n"
        "      narrative — the question is about how something works, not where\n"
        "                  something is.\n"
        "      graph     — the question is about relationships between code:\n"
        "                  what calls, what imports, what breaks if this changes.\n"
        "                  Vector search cannot answer these at all.\n"
        "  - Choose `entity_kinds` and `narrative_topics` ONLY from the lists given\n"
        "    below. Anything else is discarded.\n"
        "  - `symbols` and `paths`: only if the question genuinely refers to one.\n"
        "    Guessing a plausible name is worse than leaving the list empty — an\n"
        "    unknown name is dropped, and a wrong one wastes the lookup.\n"
        "  - `search_queries`: two or three short phrases in the vocabulary the CODE\n"
        "    would use, not the words the asker used. This is how a vague question\n"
        "    reaches the right source. Always give at least one.\n"
        "  - Prefer including a store over excluding it. Extra evidence is cheap; a\n"
        "    question routed away from its answer returns nothing useful."
    ),
    user=(
        "Repository: $project_name\n\n"
        "This knowledge base contains:\n"
        "  entity kinds present: $entity_kinds\n"
        "  narrative topics present: $narrative_topics\n"
        "  notable modules: $modules\n\n"
        "Question: $question\n\n"
        "Return the JSON object."
    ),
)

JUDGE_SCOPE = PromptTemplate(
    system=(
        "You decide whether a question should be answered from a particular "
        "codebase, before anything is searched.\n\n"
        "Return ONLY a JSON object, no prose and no markdown fences:\n"
        "{\n"
        '  "verdict": "code" | "chat" | "off_topic",\n'
        '  "reason": "one short sentence",\n'
        '  "reply": ""\n'
        "}\n\n"
        "The three verdicts:\n"
        "  code      — the repository could plausibly hold the answer. Anything "
        "about how this system works, what it contains, how to run, build, test, "
        "configure or change it — and anything about the subject matter this "
        "particular codebase is written to handle.\n"
        "  chat      — about you, or about this conversation: a greeting, thanks, "
        "what you can do, what was said earlier. There is nothing to search for.\n"
        "  off_topic — general knowledge, current affairs, another codebase, or a "
        "task unrelated to this repository. Searching would return the source files "
        "least unlike the question, which is worse than answering nothing.\n\n"
        "How to read the question:\n"
        "  - Read it the way this conversation reads it. A short follow-up takes "
        "its subject from the turns above: after two turns about a table of "
        "countries, 'and France?' is `code`.\n"
        "  - The repository's own subject matter is its business. A codebase "
        "written to handle elections makes questions about countries and votes "
        "questions about its data. Compare the question against what this "
        "repository is described as being — not against a general idea of what a "
        "programming question sounds like.\n"
        "  - When it could go either way, answer `code`. A search that comes back "
        "with nothing costs seconds; refusing a real question about somebody's own "
        "code is the failure that matters, and they cannot tell it from a product "
        "that is simply broken.\n\n"
        "The `reply` field:\n"
        "  - An empty string when the verdict is `code`. Nothing is shown.\n"
        "  - Otherwise one or two sentences, addressed to the asker. For `chat`, "
        "answer them briefly and say what they can ask about here. For "
        "`off_topic`, say plainly that this is not something you answer from this "
        "repository, and name something it does answer.\n"
        "  - Never answer an off-topic question itself, not even partly. You are "
        "the way in to one codebase, not a general assistant."
    ),
    user=(
        "$profile\n\n"
        "Earlier in this conversation:\n$history\n\n"
        "Question: $question\n\n"
        "Return the JSON object."
    ),
)

__all__ = ["JUDGE_SCOPE", "ROUTE_QUESTION"]

THREAD_TITLE = PromptTemplate(
    system=(
        "Name this conversation, for a list of conversations in a sidebar.\n\n"
        "Respond ONLY with valid JSON - no markdown fences, no prose:\n"
        '{"title": "..."}\n\n'
        "Rules:\n"
        "  - Three to six words. It sits in a narrow column and must not wrap.\n"
        "  - Describe what was actually discussed, not how the person opened. Many "
        "conversations start with a greeting, and a list of rows reading 'Hi there' "
        "is a list nobody can navigate - which is the whole reason this exists.\n"
        "  - Name the real subject where there is one: a module, a mechanism, a file. "
        "'Face attribute detection' beats 'Discussion about a feature'.\n"
        "  - Sentence case, no trailing punctuation, no quotes around it."
    ),
    user="Question:\n$question\n\nAnswer:\n$answer",
)
