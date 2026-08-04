"""
Turning parsed source into knowledge-base rows.

Pure functions with no database and no LLM, so they are cheap to test and produce
the same result every run. This is the deterministic backbone the generated prose is
later checked against.

Everything language-specific is delegated to a `LanguageProvider`; nothing here
branches on a language name.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.knowledge.constants import EntityKind
from app.knowledge.roles import infer_role
from app.languages import registry
from app.languages.base import DetectedEntity
from app.languages.taxonomy import ModuleKind

#: Entity kinds a provider is allowed to emit. Anything else is dropped rather than
#: silently persisted with a bogus kind.
_VALID_ENTITY_KINDS = {str(k) for k in EntityKind}


@dataclass(slots=True)
class SourceFile:
    """One file to analyse. Decoupled from the ingestion dataclasses on purpose."""

    path: str
    content: str
    language: str | None = None


@dataclass(slots=True)
class BuildResult:
    modules: list[dict] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    languages: Counter = field(default_factory=Counter)
    skipped: int = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "modules": len(self.modules),
            "entities": len(self.entities),
            "languages": dict(self.languages),
            "skipped_files": self.skipped,
        }


def build_modules(files: list[SourceFile]) -> BuildResult:
    """
    Group files into modules and extract their symbols and entities.

    Files whose extension no provider claims are counted in `skipped` — they are not
    an error, just outside what we can analyse structurally today.
    """
    result = BuildResult()
    grouped: dict[str, dict] = {}
    entities: list[dict] = []
    # (kind, name) → first occurrence, so a var read in ten files is recorded once.
    seen_entities: set[tuple[str, str]] = set()

    for file in files:
        if registry.should_skip(file.path):
            continue

        # Manifests are matched by filename, not extension — pyproject.toml and
        # go.mod carry dependency facts even though no provider owns .toml/.mod.
        for manifest_provider in registry.manifest_providers(file.path):
            for detected in manifest_provider.parse_manifest(file.path, file.content):
                _collect(detected, file.path, entities, seen_entities)

        provider = registry.for_path(file.path)
        if provider is None:
            result.skipped += 1
            continue

        result.languages[provider.language] += 1
        symbols = provider.extract_symbols(file.content, file.path)
        ref = provider.module_ref_for(file.path)

        bucket = grouped.setdefault(
            ref.key,
            {
                "path": ref.key,
                "name": ref.name,
                "kind": str(ref.kind or ModuleKind.UNKNOWN),
                "language": provider.language,
                "file_count": 0,
                "loc": 0,
                "is_test": True,          # AND-ed below: a module is a test module
                "symbols_json": [],       # only when every file in it is a test
                "files_json": [],
            },
        )
        bucket["file_count"] += 1
        bucket["loc"] += file.content.count("\n") + 1
        bucket["files_json"].append(file.path)
        bucket["symbols_json"].extend(s.to_dict() for s in symbols)
        bucket["is_test"] = bucket["is_test"] and provider.is_test_file(file.path)

        for detected in provider.detect_entities(file.path, file.content, symbols):
            _collect(detected, file.path, entities, seen_entities)

    for bucket in grouped.values():
        bucket["role"] = str(infer_role(bucket["path"], bucket["files_json"], bucket["is_test"]))
        result.modules.append(bucket)

    result.modules.sort(key=lambda m: m["loc"], reverse=True)
    result.entities = entities
    return result


def _collect(
    detected: DetectedEntity,
    source_path: str,
    out: list[dict],
    seen: set[tuple[str, str]],
) -> None:
    kind = str(detected.kind)
    if kind not in _VALID_ENTITY_KINDS:
        return
    key = (kind, detected.name)
    if key in seen:
        return
    seen.add(key)
    out.append(
        {
            "kind": kind,
            "name": detected.name,
            "data_json": detected.data or {},
            "source_path": source_path,
            "source_line": detected.line,
        }
    )


def entities_from_api_specs(api_specs: list) -> list[dict]:
    """
    Routes declared in OpenAPI documents.

    Language-neutral by construction — a spec describes the HTTP surface whatever
    implements it — so this complements the provider-detected routes.
    """
    out: list[dict] = []
    for spec in api_specs or []:
        for endpoint in getattr(spec, "endpoints", []) or []:
            method = str(endpoint.get("method", "")).upper() if isinstance(endpoint, dict) else ""
            path = endpoint.get("path", "") if isinstance(endpoint, dict) else ""
            if not path:
                continue
            out.append(
                {
                    "kind": str(EntityKind.ROUTE),
                    "name": f"{method} {path}".strip(),
                    "data_json": {
                        "method": method or None,
                        "path": path,
                        "source": "openapi",
                        "summary": endpoint.get("summary") if isinstance(endpoint, dict) else None,
                    },
                    "source_path": getattr(spec, "path", None),
                    "source_line": None,
                }
            )
    return out


def entities_from_infra(infra_context: list) -> list[dict]:
    """Infrastructure definitions (Docker, Kubernetes, Terraform, ...)."""
    out: list[dict] = []
    for infra in infra_context or []:
        path = getattr(infra, "path", None)
        kind = getattr(infra, "kind", None) or getattr(infra, "infra_type", None) or "infra"
        out.append(
            {
                "kind": str(EntityKind.INFRA_RESOURCE),
                "name": str(path or kind),
                "data_json": {
                    "type": str(kind),
                    "summary": (
                        infra.summary() if hasattr(infra, "summary") else None
                    ),
                },
                "source_path": str(path) if path else None,
                "source_line": None,
            }
        )
    return out


def merge_entities(*groups: list[dict]) -> list[dict]:
    """Concatenate entity groups, dropping duplicates on (kind, name)."""
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for entity in group:
            key = (entity["kind"], entity["name"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(entity)
    return merged


def chunk_files(
    files: list[SourceFile], chunk_lines: int = 40, overlap: int = 5, max_chars: int = 1500
) -> list[dict]:
    """
    Split files into overlapping chunks ready for embedding.

    Returns dicts shaped for `CodeChunk`, minus the embedding, so the caller can
    embed them in batches.
    """
    chunks: list[dict] = []
    step = max(1, chunk_lines - overlap)

    for file in files:
        if registry.should_skip(file.path):
            continue
        provider = registry.for_path(file.path)
        lines = file.content.splitlines()
        if not lines:
            continue

        for start in range(0, len(lines), step):
            end = min(start + chunk_lines, len(lines))
            text = "\n".join(lines[start:end])
            if not text.strip():
                continue
            chunks.append(
                {
                    "source_path": file.path,
                    "language": provider.language if provider else file.language,
                    "chunk_type": "code",
                    "content": text[:max_chars],
                    "start_line": start + 1,
                    "end_line": end,
                }
            )
            if end >= len(lines):
                break
    return chunks


def read_manifest_files(root, max_depth: int = 2) -> list[SourceFile]:
    """
    Find dependency manifests on disk.

    Needed because the code parser only yields files whose extension maps to a
    language — `pyproject.toml`, `go.mod` and `package.json` never appear in a
    `ParsedCodebase`, so without this the manifest hook is starved of input and the KB
    records zero dependencies.

    Shallow by design: a manifest deeper than a couple of levels is usually a vendored
    or nested package, not the project's own.
    """
    from pathlib import Path

    root = Path(root)
    if not root.is_dir():
        return []

    wanted: set[str] = set()
    for provider in registry.providers():
        wanted.update(provider.manifest_files)

    out: list[SourceFile] = []
    for name in sorted(wanted):
        for path in root.glob(f"{'*/' * 0}{name}"):
            out.append(_read_manifest(path, root))
        for depth in range(1, max_depth + 1):
            for path in root.glob("/".join(["*"] * depth) + f"/{name}"):
                if not registry.should_skip(str(path.relative_to(root))):
                    out.append(_read_manifest(path, root))
    return [f for f in out if f is not None]


def _read_manifest(path, root) -> SourceFile | None:
    try:
        return SourceFile(
            path=str(path.relative_to(root)),
            content=path.read_text(encoding="utf-8", errors="ignore"),
        )
    except OSError:
        return None


def language_breakdown(modules: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for module in modules:
        if module.get("language"):
            counts[module["language"]] += module.get("file_count", 0)
    return dict(counts)


__all__ = [
    "SourceFile",
    "BuildResult",
    "build_modules",
    "entities_from_api_specs",
    "entities_from_infra",
    "merge_entities",
    "chunk_files",
    "read_manifest_files",
    "language_breakdown",
]
