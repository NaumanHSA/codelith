"""
Inferring what a module is *for*.

Role drives section planning during composition — an API reference cares about `api`
and `schema` modules, a deployment guide about `infra`. Inference is by path
convention, which is broadly shared across ecosystems (`controllers/`, `handlers/`,
`models/`, `migrations/`), so this stays language-neutral. A language whose community
uses different names can be handled by extending `_ROLE_HINTS`.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from app.knowledge.constants import ModuleRole

#: Ordered most-specific first — the first hint found in the path segments wins.
_ROLE_HINTS: tuple[tuple[ModuleRole, tuple[str, ...]], ...] = (
    (ModuleRole.TEST, ("test", "tests", "testing", "spec", "specs", "__tests__")),
    (ModuleRole.API, ("api", "routes", "routers", "controllers", "handlers",
                      "endpoints", "views", "resources")),
    (ModuleRole.SCHEMA, ("schemas", "schema", "dto", "dtos", "serializers",
                         "types", "contracts")),
    (ModuleRole.MODEL, ("models", "entities", "domain", "orm")),
    (ModuleRole.DATA_ACCESS, ("repositories", "repository", "dao", "store", "stores",
                              "db", "database", "migrations", "queries", "memory")),
    (ModuleRole.SERVICE, ("services", "service", "usecases", "use_cases", "application",
                          "core", "business", "agents", "workflows", "ingestion",
                          "pipeline", "pipelines")),
    (ModuleRole.WORKER, ("workers", "worker", "tasks", "jobs", "queue",
                         "consumers", "celery")),
    (ModuleRole.UI, ("ui", "components", "pages", "views", "screens", "frontend", "client", "web")),
    (ModuleRole.CLI, ("cli", "commands", "cmd", "console", "bin", "scripts")),
    (ModuleRole.CONFIG, ("config", "configuration", "settings", "conf")),
    (ModuleRole.INFRA, ("infra", "infrastructure", "deploy", "deployment", "k8s",
                        "kubernetes", "terraform", "helm", "docker", "ops")),
    (ModuleRole.UTILITY, ("utils", "util", "helpers", "common", "shared", "lib",
                          "internal", "observability", "tracing", "telemetry",
                          "monitoring", "parsers", "formatters")),
)

#: Filenames that identify a module's role regardless of directory.
_FILENAME_HINTS: tuple[tuple[ModuleRole, tuple[str, ...]], ...] = (
    (ModuleRole.INFRA, ("dockerfile", "docker-compose.yml", "docker-compose.yaml")),
    (ModuleRole.CONFIG, ("settings.py", "config.py", "conf.py")),
)


def infer_role(module_path: str, file_paths: list[str], is_test: bool = False) -> ModuleRole:
    """
    Best-effort role for a module.

    `is_test` wins outright — a test module is a test module whatever it exercises.
    """
    if is_test:
        return ModuleRole.TEST

    segments = {s.lower() for s in PurePosixPath(module_path).parts}
    for role, hints in _ROLE_HINTS:
        if segments & set(hints):
            return role

    names = {PurePosixPath(p).name.lower() for p in file_paths}
    for role, hints in _FILENAME_HINTS:
        if names & set(hints):
            return role

    return ModuleRole.UNKNOWN


def suggest_doc_types(entity_kinds: dict[str, int], roles: dict[str, int]) -> list[dict]:
    """
    Which document types are worth offering, given what analysis found.

    This is the payoff of choosing the doc type *after* analysis: the options are
    evidence-backed rather than a fixed menu. Returns dicts matching
    `app.schemas.knowledge.DocTypeSuggestion`.
    """
    from app.knowledge.constants import EntityKind

    routes = entity_kinds.get(EntityKind.ROUTE, 0)
    infra = entity_kinds.get(EntityKind.INFRA_RESOURCE, 0)
    deps = entity_kinds.get(EntityKind.DEPENDENCY, 0)
    entrypoints = entity_kinds.get(EntityKind.ENTRYPOINT, 0)
    total_modules = sum(roles.values()) or 1

    suggestions: list[dict] = [
        {
            "doc_type": "architecture",
            "confidence": 0.9,
            "reason": f"{total_modules} modules mapped across the codebase",
        }
    ]

    if routes:
        suggestions.append({
            "doc_type": "api",
            "confidence": min(0.95, 0.6 + routes / 40),
            "reason": f"{routes} HTTP routes detected",
        })
    if infra:
        suggestions.append({
            "doc_type": "deployment",
            "confidence": min(0.9, 0.5 + infra / 10),
            "reason": f"{infra} infrastructure definitions found",
        })
    if entrypoints or deps:
        suggestions.append({
            "doc_type": "getting_started",
            "confidence": 0.7 if entrypoints else 0.5,
            "reason": (
                f"{entrypoints} entrypoints and {deps} declared dependencies"
                if entrypoints else f"{deps} declared dependencies"
            ),
        })
    if roles.get(ModuleRole.SERVICE, 0) + roles.get(ModuleRole.UTILITY, 0) >= 3:
        suggestions.append({
            "doc_type": "modules",
            "confidence": 0.6,
            "reason": "several service and utility modules worth documenting individually",
        })

    return sorted(suggestions, key=lambda s: s["confidence"], reverse=True)


__all__ = ["infer_role", "suggest_doc_types"]
