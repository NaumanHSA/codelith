"""
Assembling the code graph from provider output.

The division of labour matters here. Providers know how to *read* a language —
which lines are imports, what a call site looks like, how a dotted path maps onto a
file. This module knows nothing about any language; it walks files, asks whichever
provider owns each one, and stitches the answers into a `CodeGraph`.

That is why the whole thing is testable without Neo4j and without a repository: it
is a pure function from files to a graph.

**Call resolution is deliberately narrow.** A call to `run()` is resolved only if the
same file defines `run`, or the file explicitly imported `run` from a file that does.
Matching by name across the whole repository would connect every `run` to every other
one — a graph that looks impressively dense and means nothing. Precision over recall:
an edge that exists should be trustworthy, and impact analysis that over-reports is
indistinguishable from noise.
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from app.knowledge.builder import SourceFile
from app.languages.registry import registry
from app.memory.graph_store import CodeGraph

logger = structlog.get_logger(__name__)

#: Calls recorded per file. A generated or vendored file can contain thousands, and
#: past a point they stop describing structure and start describing volume.
_MAX_CALLS_PER_FILE = 400


def build_code_graph(
    files: list[SourceFile],
    module_roles: dict[str, str] | None = None,
) -> CodeGraph:
    """
    A `CodeGraph` for these files.

    `module_roles` maps a module key to the role the extractor assigned it
    (`service`, `api`, `data_access`, …), so the graph carries the same vocabulary as
    the rest of the knowledge base rather than inventing a second one.
    """
    roles = module_roles or {}
    known_files = frozenset(f.path for f in files)

    graph = CodeGraph()
    modules_seen: dict[str, dict] = {}

    #: path -> {symbol name -> qname}, for resolving calls within a file.
    defined: dict[str, dict[str, str]] = defaultdict(dict)
    #: path -> [(imported name, resolved file)], for resolving calls across files.
    imported_names: dict[str, list[tuple[str, str]]] = defaultdict(list)
    #: Deferred so every file's symbols are known before any call is resolved.
    pending_calls: list[tuple[str, object]] = []
    import_edges: set[tuple[str, str]] = set()
    package_edges: set[tuple[str, str]] = set()

    for source in files:
        provider = registry.for_path(source.path)
        if provider is None:
            continue

        module = provider.module_ref_for(source.path)
        if module.key not in modules_seen:
            modules_seen[module.key] = {
                "key": module.key,
                "name": module.name,
                "role": roles.get(module.key, "unknown"),
            }

        graph.files.append({
            "path": source.path,
            "language": provider.language,
            "module_key": module.key,
            "loc": source.content.count("\n") + 1,
        })

        for symbol in provider.extract_symbols(source.content, source.path):
            qname = symbol.qualified_name
            graph.symbols.append({
                "path": source.path,
                "qname": qname,
                "name": symbol.name,
                "kind": str(symbol.kind),
                "line": symbol.line,
                "end_line": symbol.end_line,
                "visibility": str(symbol.visibility),
            })
            # First definition wins: a name redefined in one file is ambiguous, and
            # picking the later one would silently retarget existing edges.
            defined[source.path].setdefault(symbol.name, qname)

        for ref in provider.extract_imports(source.content, source.path):
            target = provider.resolve_import(ref, source.path, known_files)
            if target and target != source.path:
                # Deduped: one file importing three names from another is one edge,
                # and a test file with the same import inside four functions is one
                # edge too. Neo4j would MERGE them anyway; this saves the write.
                import_edges.add((source.path, target))
                for name in ref.names:
                    imported_names[source.path].append((name, target))
            elif not target and (package := provider.external_package(ref)):
                package_edges.add((source.path, package))

        calls = provider.extract_calls(source.content, source.path)
        if calls:
            pending_calls.append((source.path, calls[:_MAX_CALLS_PER_FILE]))

    graph.modules = list(modules_seen.values())
    graph.imports = [{"src": a, "dst": b} for a, b in sorted(import_edges)]
    graph.packages = [{"src": a, "name": b} for a, b in sorted(package_edges)]
    graph.calls = _resolve_calls(pending_calls, defined, imported_names)

    logger.info("code_graph_built", **graph.counts())
    return graph


def _resolve_calls(
    pending: list[tuple[str, object]],
    defined: dict[str, dict[str, str]],
    imported_names: dict[str, list[tuple[str, str]]],
) -> list[dict]:
    """Call sites that resolve to a symbol we actually saw. The rest are dropped."""
    edges: set[tuple[str, str, str, str]] = set()

    for path, calls in pending:
        local = defined.get(path, {})
        imports = imported_names.get(path, [])

        for call in calls:  # type: ignore[union-attr]
            # `caller` is already a qualified name — providers emit it in the same
            # shape as `Symbol.qualified_name`. An edge from a caller we never
            # recorded as a symbol would dangle, so it is dropped.
            if call.caller not in local.values():
                continue

            if target_q := local.get(call.callee):
                edges.add((path, call.caller, path, target_q))
                continue

            # Otherwise: a file this one imports from. `svc.rekey_anchor()` gives us
            # only `rekey_anchor`, so a bare-name import (`from x import helper`) and
            # a method on an imported class both arrive here identically.
            #
            # Linked only when exactly one imported file defines the name. Two
            # imported modules that both define `run` make the call ambiguous, and
            # picking either is how a call graph becomes confidently wrong.
            candidates = {
                (target_path, qname)
                for _, target_path in imports
                if (qname := defined.get(target_path, {}).get(call.callee))
            }
            if len(candidates) == 1:
                target_path, qname = candidates.pop()
                edges.add((path, call.caller, target_path, qname))

    return [
        {"src_path": sp, "src_qname": sq, "dst_path": dp, "dst_qname": dq}
        for sp, sq, dp, dq in sorted(edges)
    ]


__all__ = ["build_code_graph"]
