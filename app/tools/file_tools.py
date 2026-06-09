from pathlib import Path


def read_file(path: str, max_chars: int = 8000) -> str:
    try:
        content = Path(path).read_text(encoding="utf-8", errors="ignore")
        return content[:max_chars]
    except OSError as exc:
        return f"Error reading {path}: {exc}"


def list_directory(path: str, extensions: list[str] | None = None) -> list[str]:
    root = Path(path)
    if not root.exists():
        return []
    result = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if extensions and p.suffix not in extensions:
            continue
        result.append(str(p.relative_to(root)))
    return result


def search_in_file(path: str, query: str, context_lines: int = 3) -> list[dict]:
    """Return snippets around lines matching query (case-insensitive)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    q = query.lower()
    matches = []
    for i, line in enumerate(lines):
        if q in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            matches.append({
                "line": i + 1,
                "match": line.strip(),
                "context": "\n".join(lines[start:end]),
            })
    return matches[:20]
