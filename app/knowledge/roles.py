"""
Inferring what a module is *for*.

Role is not cosmetic. It decides which narratives get written (`_ROLE_TRIGGERS`),
which modules the planner is shown per document type (`_ROLE_FOCUS`), and how the
deterministic architecture fallback groups the codebase. A module that infers to
`unknown` is invisible to all three, so `unknown` has to mean "genuinely
undecidable", not "our word list was short".

Measured on run 1 (neurosurfer, 45 modules) the previous path-only matcher put 23
modules — 13,770 LOC, more than every other role combined — on `unknown`. Three
things caused it, and each is addressed here:

  * **Singular/plural mismatch.** The hint list held `workflows` but the module was
    `neurosurfer/graph/workflow`. Segments and hints are now compared in a
    normalised singular form, which removes the whole class of near-misses.
  * **No use of the evidence we already extracted.** A module whose files define
    HTTP routes *is* the API layer whatever its directory is called. Detected
    entities now outrank path convention.
  * **`unknown` as the fallback.** A module full of public symbols that matched no
    keyword is a service we failed to name, not an unknowable. It now falls back to
    `service`, leaving `unknown` for modules with nothing to go on.

Inference stays language-neutral: path convention plus entity kinds, both of which
are shared across ecosystems. A language whose community uses different names is
handled by extending `_ROLE_HINTS`.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath

from app.knowledge.constants import EntityKind, ModuleRole

#: Ordered most-specific first — the first hint found in the path segments wins.
#: Written in singular form; `_normalise` folds plurals onto it, so `route` also
#: matches `routes` and `workflow` also matches `workflows`.
_ROLE_HINTS: tuple[tuple[ModuleRole, tuple[str, ...]], ...] = (
    (ModuleRole.TEST, ("test", "testing", "spec", "__tests__", "e2e", "fixture")),
    (ModuleRole.API, ("api", "route", "router", "controller", "handler", "endpoint",
                      "resource", "rest", "graphql", "grpc", "rpc", "server", "http")),
    (ModuleRole.SCHEMA, ("schema", "dto", "serializer", "type", "contract",
                         "protocol", "interface", "proto")),
    (ModuleRole.MODEL, ("model", "entity", "domain", "orm", "record")),
    (ModuleRole.DATA_ACCESS, ("repository", "repo", "dao", "store", "vectorstore",
                              "db", "database", "migration", "query", "memory",
                              "cache", "persistence", "storage", "index")),
    (ModuleRole.WORKER, ("worker", "task", "job", "queue", "consumer", "celery",
                         "scheduler", "cron")),
    (ModuleRole.SERVICE, ("service", "usecase", "use_case", "application", "core",
                          "business", "agent", "workflow", "orchestration",
                          "orchestrator", "engine", "runtime", "graph", "pipeline",
                          "ingestion", "processing", "manager", "provider", "backend",
                          "adapter", "client", "integration", "plugin", "tool",
                          "llm", "rag", "mcp")),
    (ModuleRole.UI, ("ui", "component", "page", "view", "screen", "frontend",
                     "widget", "layout")),
    (ModuleRole.CLI, ("cli", "command", "cmd", "console", "bin", "script", "shell")),
    (ModuleRole.CONFIG, ("config", "configuration", "setting", "conf", "env",
                         "prompt", "template")),
    (ModuleRole.INFRA, ("infra", "infrastructure", "deploy", "deployment", "k8s",
                        "kubernetes", "terraform", "helm", "docker", "ops",
                        "provisioning")),
    (ModuleRole.UTILITY, ("util", "helper", "common", "shared", "lib", "internal",
                          "observability", "tracing", "telemetry", "monitoring",
                          "metric", "logging", "parser", "formatter", "exporter",
                          "tutorial", "example", "sample", "demo")),
)

#: Filenames that identify a module's role regardless of directory. Applied only when
#: they *dominate* the module — one `config.py` among thirteen files says nothing
#: about the module, and used to relabel a whole RAG package as `config`.
_FILENAME_HINTS: tuple[tuple[ModuleRole, tuple[str, ...]], ...] = (
    (ModuleRole.INFRA, ("dockerfile", "docker-compose.yml", "docker-compose.yaml")),
    (ModuleRole.CONFIG, ("settings.py", "config.py", "conf.py")),
)

#: Detected entity kind → what owning one says about the module. This outranks path
#: convention: it is observed fact rather than naming convention.
_ENTITY_ROLES: tuple[tuple[EntityKind, ModuleRole], ...] = (
    (EntityKind.ROUTE, ModuleRole.API),
    (EntityKind.INFRA_RESOURCE, ModuleRole.INFRA),
)

#: Below this, a module is too small to call anything but utility when nothing matched.
_MIN_SYMBOLS_FOR_SERVICE = 1


def _plurals(word: str) -> set[str]:
    """
    A hint and the plural spellings that mean the same thing.

    Expanding the *hints* rather than stemming the *segments* avoids inventing stems:
    a stemmer turned `vectorstores` into `vectorstor`, which matched nothing.
    """
    forms = {word, f"{word}s", f"{word}es"}
    if word.endswith("y"):
        forms.add(f"{word[:-1]}ies")  # repository → repositories
    return forms


#: Hints pre-expanded once, in declaration order, so lookup is a plain set test.
_EXPANDED_HINTS: tuple[tuple[ModuleRole, frozenset[str]], ...] = tuple(
    (role, frozenset().union(*(_plurals(h) for h in hints)))
    for role, hints in _ROLE_HINTS
)


def _terms(segment: str) -> set[str]:
    """One path segment as the terms it could match, including compound pieces."""
    seg = segment.lower().strip("_-")
    terms = {seg}
    # `web_search` should also offer `search`; `agentic_loop` also `loop`.
    terms.update(p for p in seg.replace("-", "_").split("_") if p)
    return terms


def _match(terms: set[str]) -> ModuleRole | None:
    for role, hints in _EXPANDED_HINTS:
        if terms & hints:
            return role
    return None


def infer_role(
    module_path: str,
    file_paths: list[str],
    is_test: bool = False,
    *,
    entity_kinds: Iterable[str] = (),
    symbol_count: int = 0,
) -> ModuleRole:
    """
    Best-effort role for a module, strongest evidence first.

    `is_test` wins outright — a test module is a test module whatever it exercises.
    Then detected entities, then path convention, then dominant filenames, and
    finally a shape-based default so that real code is never left `unknown`.
    """
    if is_test:
        return ModuleRole.TEST

    owned = {str(k) for k in entity_kinds}
    for kind, role in _ENTITY_ROLES:
        if str(kind) in owned:
            return role

    parts = PurePosixPath(module_path).parts
    # The leaf names the module; ancestors only describe where it lives. Checking the
    # leaf first stops `app/server/schemas` being called an API because of `server`.
    if parts and (role := _match(_terms(parts[-1]))):
        return role
    ancestors: set[str] = set()
    for raw in parts[:-1]:
        ancestors |= _terms(raw)
    if role := _match(ancestors):
        return role

    names = [PurePosixPath(p).name.lower() for p in file_paths]
    for role, hints in _FILENAME_HINTS:
        matched = sum(1 for n in names if n in hints)
        # Dominant means "most of the module", or "the module is one or two files".
        if matched and (len(names) <= 2 or matched * 2 >= len(names)):
            return role

    # Nothing matched. Code that exposes symbols is a service we failed to name;
    # `unknown` is reserved for modules with nothing to go on at all.
    if symbol_count >= _MIN_SYMBOLS_FOR_SERVICE:
        return ModuleRole.SERVICE
    return ModuleRole.UNKNOWN


def suggest_doc_types(entity_kinds: dict[str, int], roles: dict[str, int]) -> list[dict]:
    """
    Which document types are worth offering, given what analysis found.

    This is the payoff of choosing the doc type *after* analysis: the options are
    evidence-backed rather than a fixed menu. Returns dicts matching
    `app.schemas.knowledge.DocTypeSuggestion`.
    """
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
