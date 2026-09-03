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

__all__ = ["ROUTE_QUESTION"]

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
