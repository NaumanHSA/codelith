"""Each language's own rules (`LanguageProvider.inspect`), over every source file in scope."""

from __future__ import annotations

import asyncio
from collections import Counter

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.languages import registry

AREAS = frozenset({"security", "leakage", "errors", "breaks", "performance", "tests"})
TITLE = "Each language's rules, line by line"
#: The language rules name themselves (`LanguageProvider.qa_rules`).
RULES: dict[str, str] = {}

#: Files handed to the rules per trip to a worker thread.
_BATCH = 40


async def run(ctx: RunContext) -> list[Finding]:
    out: list[Finding] = []
    unchecked: Counter[str] = Counter()
    batch: list[tuple] = []

    def inspect_all(items: list[tuple]) -> list[tuple[str, list]]:
        return [(path, provider.inspect(path, text)) for provider, path, text in items]

    async def flush() -> None:
        for path, issues in await asyncio.to_thread(inspect_all, list(batch)):
            for issue in issues:
                if issue.area in ctx.areas:
                    out.append(
                        Finding(
                            rule=issue.rule,
                            area=issue.area,
                            severity=issue.severity,
                            title=issue.title,
                            message=issue.message,
                            fix=issue.fix,
                            path=path,
                            line=issue.line,
                            end_line=issue.end_line,
                            confidence=issue.confidence,
                            source="rule",
                        )
                    )
        batch.clear()
        await ctx.checkpoint()

    for f in ctx.files:
        if f.kind is not None:
            continue  # project files are the neutral checks' business
        provider = registry.for_path(f.path)
        if provider is None:
            continue
        if not provider.has_rules:
            unchecked[provider.display_name] += 1
            continue
        batch.append((provider, f.path, await ctx.text(f)))
        if len(batch) >= _BATCH:
            await flush()
    if batch:
        await flush()

    for language, n in sorted(unchecked.items()):
        ctx.notes.append(f"There are no rules for {language} yet: {n} file(s) were not checked line by line.")
    return out


__all__ = ["AREAS", "TITLE", "run"]
