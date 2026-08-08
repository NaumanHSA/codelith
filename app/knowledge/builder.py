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

from app.knowledge import policy
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

    # Entity kinds owned per file, so role inference can use what was actually
    # detected — a module defining HTTP routes is the API layer whatever it is called.
    kinds_by_file: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        if path := entity.get("source_path"):
            kinds_by_file[path].add(entity["kind"])

    for bucket in grouped.values():
        owned: set[str] = set()
        for path in bucket["files_json"]:
            owned |= kinds_by_file.get(path, set())
        bucket["role"] = str(
            infer_role(
                bucket["path"],
                bucket["files_json"],
                bucket["is_test"],
                entity_kinds=owned,
                symbol_count=len(bucket["symbols_json"]),
            )
        )
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
    files: list[SourceFile],
    chunk_lines: int = 40,
    overlap: int = 5,
    max_chars: int = 4000,
) -> list[dict]:
    """
    Split files into chunks ready for embedding, on symbol boundaries where possible.

    The provider has already extracted every declaration with its line span, so a
    chunk can be a whole function or class instead of an arbitrary 40-line window.
    Files no provider claims — and the gaps between declarations — fall back to line
    windows.

    Two properties matter and are tested:

      * **`start_line`/`end_line` describe the text that is actually stored.** The
        previous version cut a window to 1,500 chars while still reporting the full
        40-line span; 34% of run 1's chunks were affected, and the retrieval layer
        labelled every one of them `path:start-end` as though it were complete.
      * **Oversized units are split, not truncated.** A 900-line class becomes several
        chunks with honest spans rather than one chunk holding its first 1,500 chars.
    """
    chunks: list[dict] = []

    for file in files:
        if registry.should_skip(file.path):
            continue
        provider = registry.for_path(file.path)
        lines = file.content.splitlines()
        if not lines:
            continue

        language = provider.language if provider else file.language
        spans = _symbol_spans(provider, file, len(lines))
        if not spans:
            spans = _window_spans(len(lines), chunk_lines, overlap)
        spans = _merge_small(spans, lines, max_chars)

        for start, end in spans:
            chunks.extend(
                _emit(file.path, language, lines, start, end, max_chars, chunk_lines)
            )

        # Docstrings, separately from the code that carries them. They are already in
        # a code chunk verbatim, but as prose they answer a different kind of question
        # — intent rather than mechanism — and they have to be *addressable* as prose
        # for a policy to be able to exclude them. See `app/knowledge/policy.py`.
        chunks.extend(_docstring_chunks(provider, file, language))

    return chunks


def chunk_prose(docs: list[SourceFile], max_chars: int = 4000) -> list[dict]:
    """
    Markdown split on its own headings.

    A README is a router: it says where to look, not what is true. Splitting on
    headings keeps each chunk answering one question, which is what makes it useful
    for pointing at code rather than for being quoted.
    """
    chunks: list[dict] = []
    for doc in docs:
        if registry.should_skip(doc.path):
            continue
        lines = doc.content.splitlines()
        if not lines:
            continue

        for start, end in _heading_spans(lines):
            body = "\n".join(lines[start - 1 : end]).strip()
            if not body:
                continue
            for offset in range(0, len(body), max_chars):
                piece = body[offset : offset + max_chars]
                chunks.append({
                    "source_path": doc.path,
                    "language": "markdown",
                    "chunk_type": policy.MARKDOWN,
                    "content": piece,
                    "start_line": start,
                    "end_line": end,
                })
    return chunks


def _heading_spans(lines: list[str]) -> list[tuple[int, int]]:
    """`(start, end)` per markdown section, 1-based and inclusive. Fence-aware."""
    starts: list[int] = []
    in_fence = False
    for index, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("#"):
            starts.append(index)

    if not starts:
        return [(1, len(lines))]
    # Text before the first heading is a section too — often the whole point of a README.
    if starts[0] > 1:
        starts.insert(0, 1)
    return [
        (start, (starts[i + 1] - 1) if i + 1 < len(starts) else len(lines))
        for i, start in enumerate(starts)
    ]


def _docstring_chunks(provider, file: SourceFile, language: str | None) -> list[dict]:
    """One chunk per documented declaration, plus the module docstring."""
    if provider is None:
        return []
    out: list[dict] = []
    for symbol in provider.extract_symbols(file.content, file.path):
        text = (symbol.docstring or "").strip()
        # One-liners are labels, not intent, and they dilute the prose pool.
        if len(text) < 80:
            continue
        out.append({
            "source_path": file.path,
            "language": language,
            "chunk_type": policy.DOCSTRING,
            "content": f"{symbol.qualified_name}: {text}",
            "start_line": symbol.line,
            "end_line": symbol.end_line or symbol.line,
        })
    return out


def _symbol_spans(provider, file: SourceFile, total_lines: int) -> list[tuple[int, int]]:
    """
    Line spans covering a file: one per top-level declaration, plus the gaps between.

    Gaps matter — imports, module-level constants and dispatch code live there, and a
    symbol-only scheme would leave them unembedded and therefore unretrievable.
    """
    if provider is None:
        return []
    try:
        symbols = provider.extract_symbols(file.content, file.path)
    except Exception:
        return []

    units = sorted(
        (
            (s.line, s.end_line or s.line)
            for s in symbols
            if not s.parent and s.line and s.line <= total_lines
        ),
    )
    if not units:
        return []

    spans: list[tuple[int, int]] = []
    cursor = 1
    for start, end in units:
        if start > cursor:
            spans.append((cursor, start - 1))          # the gap before this declaration
        spans.append((start, min(end, total_lines)))
        cursor = max(cursor, min(end, total_lines) + 1)
    if cursor <= total_lines:
        spans.append((cursor, total_lines))
    return spans


#: A chunk below this is not worth an embedding of its own — a lone `MAX_RETRIES = 3`
#: retrieves nothing useful and costs a row. Small neighbours are merged up to it.
_MIN_CHUNK_CHARS = 400


def _merge_small(
    spans: list[tuple[int, int]], lines: list[str], max_chars: int
) -> list[tuple[int, int]]:
    """Coalesce adjacent spans until each is worth embedding, without exceeding budget."""
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged:
            prev_start, prev_end = merged[-1]
            prev_size = sum(len(line) + 1 for line in lines[prev_start - 1:prev_end])
            this_size = sum(len(line) + 1 for line in lines[start - 1:end])
            if prev_size < _MIN_CHUNK_CHARS and prev_size + this_size <= max_chars:
                merged[-1] = (prev_start, end)
                continue
        merged.append((start, end))
    return merged


def _window_spans(total_lines: int, chunk_lines: int, overlap: int) -> list[tuple[int, int]]:
    """Fixed overlapping windows — the fallback for files with no extractable symbols."""
    step = max(1, chunk_lines - overlap)
    spans: list[tuple[int, int]] = []
    for start in range(0, total_lines, step):
        end = min(start + chunk_lines, total_lines)
        spans.append((start + 1, end))
        if end >= total_lines:
            break
    return spans


def _emit(
    path: str,
    language: str | None,
    lines: list[str],
    start: int,
    end: int,
    max_chars: int,
    chunk_lines: int,
) -> list[dict]:
    """
    One span → one or more chunks, each reporting the lines it really contains.

    A span longer than the character budget is split at a line boundary rather than
    truncated, so no source silently disappears from the index.
    """
    out: list[dict] = []
    cursor = start
    while cursor <= end:
        stop = cursor
        size = 0
        while stop <= end:
            line_len = len(lines[stop - 1]) + 1
            if size + line_len > max_chars and stop > cursor:
                break
            size += line_len
            stop += 1
            if stop - cursor >= chunk_lines * 4:  # keep any one chunk sane
                break

        body = lines[cursor - 1:stop - 1]
        # Trim blank edges and move the reported span with them. Trailing blanks vanish
        # on any splitlines() round-trip, so keeping them would make the metadata stop
        # describing the stored text; leading blanks would make a chunk that begins at a
        # declaration look like it begins two lines earlier.
        offset = 0
        while body and not body[0].strip():
            body.pop(0)
            offset += 1
        while body and not body[-1].strip():
            body.pop()

        if body:
            first = cursor + offset
            out.append(
                {
                    "source_path": path,
                    "language": language,
                    "chunk_type": policy.CODE,
                    "content": "\n".join(body),
                    "start_line": first,
                    "end_line": first + len(body) - 1,
                }
            )
        cursor = stop
    return out


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
                if not registry.should_skip(path.relative_to(root).as_posix()):
                    out.append(_read_manifest(path, root))
    return [f for f in out if f is not None]


def _read_manifest(path, root) -> SourceFile | None:
    try:
        return SourceFile(
            path=path.relative_to(root).as_posix(),
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
