"""
Narrative topic vocabulary: which topics a codebase warrants, and who reads them.

Two questions live here, and both were previously answered in the wrong places.

**Which topics to write.** `narrative_writer` decided with hardcoded heuristics —
two always-on, role triggers, entity triggers, and substring matching on module
names. Measured on run 1 it produced 6 of 10 topics, and the misses were caused by
our word lists rather than by absent evidence; `error_handling` could not be
produced at all, because it appeared in none of the trigger tables. The heuristics
are kept here as a **floor**: topics the facts plainly justify, which a model is not
permitted to talk us out of. Everything above the floor is chosen by one cheap
selection call.

**Who reads which topic.** `SectionContextBuilder` mapped document type → topics,
correctly, while `strategy` and `planner` hardcoded `overview` + `architecture`
regardless of what was requested. For an API document that meant the stage setting
audience and tone never saw an endpoint — the routes were sitting in the
`request_lifecycle` narrative nobody passed it. One mapping now serves all three.

The vocabulary stays closed. `topic` is a lookup key: `kb_narratives.topic` is
indexed, retrieval fetches exact topics, and `topics_present()` feeds the KB stats.
A model may choose *from* `NarrativeTopic`; it may not invent members of it.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.knowledge.constants import EntityKind, ModuleRole, NarrativeTopic

#: Written for every codebase — anything can be described and has some structure.
ALWAYS: tuple[NarrativeTopic, ...] = (NarrativeTopic.OVERVIEW, NarrativeTopic.ARCHITECTURE)

#: Module role → topics that role makes worth writing.
ROLE_TRIGGERS: dict[NarrativeTopic, set[ModuleRole]] = {
    NarrativeTopic.REQUEST_LIFECYCLE: {ModuleRole.API, ModuleRole.SERVICE, ModuleRole.WORKER},
    NarrativeTopic.DATA_MODEL: {ModuleRole.MODEL, ModuleRole.DATA_ACCESS, ModuleRole.SCHEMA},
    NarrativeTopic.CONFIGURATION: {ModuleRole.CONFIG},
    NarrativeTopic.TESTING: {ModuleRole.TEST},
    NarrativeTopic.DEPLOYMENT: {ModuleRole.INFRA},
    NarrativeTopic.CLI_USAGE: {ModuleRole.CLI},
    NarrativeTopic.STATE_MANAGEMENT: {ModuleRole.DATA_ACCESS, ModuleRole.UI},
    NarrativeTopic.CONCURRENCY: {ModuleRole.WORKER},
    # Every codebase handles failure somehow, and the modules that do it are the ones
    # that also do the work. This is what made `error_handling` unreachable before:
    # it was in the enum, had prompt guidance written for it, and appeared in no
    # trigger table at all.
    NarrativeTopic.ERROR_HANDLING: {ModuleRole.SERVICE, ModuleRole.API, ModuleRole.WORKER},
    NarrativeTopic.OBSERVABILITY: {ModuleRole.UTILITY},
}

#: Detected entity kind → topics that evidence makes worth writing.
ENTITY_TRIGGERS: dict[NarrativeTopic, set[EntityKind]] = {
    NarrativeTopic.DEPLOYMENT: {EntityKind.INFRA_RESOURCE},
    NarrativeTopic.CONFIGURATION: {EntityKind.ENV_VAR},
    NarrativeTopic.INTEGRATIONS: {EntityKind.EXTERNAL_API},
    NarrativeTopic.REQUEST_LIFECYCLE: {EntityKind.ROUTE},
    NarrativeTopic.CLI_USAGE: {EntityKind.ENTRYPOINT},
    NarrativeTopic.BUILD_AND_RELEASE: {EntityKind.DEPENDENCY},
}

#: Which narratives each document type reads. The single source of truth for
#: strategy, the planner and section retrieval.
DOC_TYPE_TOPICS: dict[str, tuple[NarrativeTopic, ...]] = {
    "architecture": (
        NarrativeTopic.ARCHITECTURE,
        NarrativeTopic.OVERVIEW,
        NarrativeTopic.CONCURRENCY,
        NarrativeTopic.EXTENSIBILITY,
    ),
    "api": (
        NarrativeTopic.REQUEST_LIFECYCLE,
        NarrativeTopic.AUTH,
        NarrativeTopic.DATA_MODEL,
        NarrativeTopic.ERROR_HANDLING,
        NarrativeTopic.OVERVIEW,
    ),
    "deployment": (
        NarrativeTopic.DEPLOYMENT,
        NarrativeTopic.CONFIGURATION,
        NarrativeTopic.OBSERVABILITY,
        NarrativeTopic.BUILD_AND_RELEASE,
    ),
    "getting_started": (
        NarrativeTopic.OVERVIEW,
        NarrativeTopic.CONFIGURATION,
        NarrativeTopic.CLI_USAGE,
        NarrativeTopic.BUILD_AND_RELEASE,
    ),
    "modules": (
        NarrativeTopic.ARCHITECTURE,
        NarrativeTopic.EXTENSIBILITY,
        NarrativeTopic.STATE_MANAGEMENT,
    ),
    "testing": (NarrativeTopic.TESTING, NarrativeTopic.ARCHITECTURE),
}

#: Fallback for a document type with no explicit mapping.
_DEFAULT_TOPICS: tuple[NarrativeTopic, ...] = (
    NarrativeTopic.OVERVIEW,
    NarrativeTopic.ARCHITECTURE,
)


def topics_for_doc_type(doc_type: str) -> tuple[NarrativeTopic, ...]:
    """Narratives worth showing a stage that is working on `doc_type`."""
    return DOC_TYPE_TOPICS.get((doc_type or "").lower(), _DEFAULT_TOPICS)


#: Module-name substrings that suggest an authentication story. There is no entity
#: kind for auth, so this stays a name heuristic — but only as a *floor* signal, where
#: a false positive costs one narrative that answers NOT_APPLICABLE. Bare "token" and
#: "identity" were dropped: both fire on unrelated code, and the selection call now
#: covers projects that name the module something else entirely.
AUTH_HINTS: tuple[str, ...] = (
    "auth", "security", "permission", "rbac", "login", "credential", "oauth", "session",
)


def required_topics(
    roles: Iterable[str],
    entity_kinds: Iterable[str],
    module_names: Iterable[str] = (),
) -> list[NarrativeTopic]:
    """
    The floor: topics the evidence plainly justifies.

    These are written whatever the selection call says. 24 env vars mean the project
    has a configuration story regardless of whether a model thought to mention it, and
    a selector having a bad day must degrade quality rather than silently drop a topic
    the facts demand.
    """
    present_roles = {str(r) for r in roles}
    present_kinds = {str(k) for k in entity_kinds}

    topics: list[NarrativeTopic] = list(ALWAYS)
    for topic, trigger_roles in ROLE_TRIGGERS.items():
        if present_roles & {str(r) for r in trigger_roles}:
            topics.append(topic)
    for topic, trigger_kinds in ENTITY_TRIGGERS.items():
        if present_kinds & {str(k) for k in trigger_kinds}:
            topics.append(topic)

    haystack = " ".join(str(n).lower() for n in module_names)
    if any(hint in haystack for hint in AUTH_HINTS):
        topics.append(NarrativeTopic.AUTH)

    return list(dict.fromkeys(topics))


def coerce_topics(raw: Iterable[str]) -> list[NarrativeTopic]:
    """
    Map model output onto the enum, discarding anything that is not a member.

    The guard behind "the model chooses from the vocabulary": a returned
    `"authentication_and_permissions"` would be written to a topic no consumer ever
    asks for, and the API document would quietly go without its auth narrative.
    """
    valid = {str(t): t for t in NarrativeTopic}
    out: list[NarrativeTopic] = []
    for item in raw or ():
        key = str(item).strip().lower().replace(" ", "_").replace("-", "_")
        if (topic := valid.get(key)) and topic not in out:
            out.append(topic)
    return out


__all__ = [
    "ALWAYS",
    "DOC_TYPE_TOPICS",
    "ENTITY_TRIGGERS",
    "ROLE_TRIGGERS",
    "coerce_topics",
    "required_topics",
    "topics_for_doc_type",
]
