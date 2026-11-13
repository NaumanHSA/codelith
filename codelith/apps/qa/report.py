"""
A run, written out: a fix plan in Markdown for people, SARIF for tools.

**The fix plan** lists what is open, most severe first and, within a severity, the
quickest to fix first — a list someone can work down, ticking boxes. Effort is a guess
from what the fix is: a patch QA wrote, or a one-line change, is small; a guard on a
route, a failing test, an untested entry point is medium; an install that fails on a
clean machine is large.

**SARIF 2.1.0** is what GitHub code scanning and most editors read. Each finding keeps
its fingerprint as `partialFingerprints`, so a tool comparing two uploads sees the same
finding as the same alert, as QA's own runs do.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from codelith.apps.qa.areas import AREA_BY_ID, SEVERITIES, SEVERITY_RANK
from codelith.apps.qa.rules import label
from codelith.models.qa import QAFinding, QARun

#: Fixes that are a line or two: a version, a flag, a declaration.
_SMALL = (
    "py.bare-except", "py.is-literal", "py.debug-on", "py.tls-off", "py.weak-hash", "py.no-timeout",
    "py.insecure-random", "py.mutable-default", "ts.tls-off", "go.tls-off", "deps.unused", "deps.unpinned",
    "deps.undeclared", "deps.dev-at-runtime", "deps.transitive-only", "deps.lock-drift", "deps.outdated",
    "compat.image", "tool.ruff",
)
_LARGE = ("breaks.install-fails",)
_EFFORT_RANK = {"small": 0, "medium": 1, "large": 2}
_SARIF_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "info": "note"}
_SECURITY_SEVERITY = {"critical": "9.5", "high": "8.0", "medium": "5.5", "low": "3.0", "info": "1.0"}


def effort(f: QAFinding) -> str:
    if f.patch or f.rule in _SMALL or f.rule.startswith(("deploy.", "config.")):
        return "small"
    if f.rule in _LARGE:
        return "large"
    return "medium"


def _where(f: QAFinding) -> str:
    if not f.path:
        return "the codebase as a whole"
    return f"`{f.path}:{f.line}`" if f.line else f"`{f.path}`"


def markdown(run: QARun, findings: list[QAFinding], project_name: str) -> str:
    """The fix plan: what is open, by severity, quickest first, each with its fix."""
    summary = run.summary_json or {}
    commit = (summary.get("commit") or "")[:8]
    when = (run.finished_at or run.created_at or datetime.now(UTC)).strftime("%Y-%m-%d")
    counts = Counter(f.severity for f in findings)
    out = [
        f"# QA fix plan — {project_name}",
        "",
        f"Run #{run.id} on {when}, at `{commit or 'unknown'}`, "
        f"{run.depth} depth, over {summary.get('scope') or 'the whole codebase'}. "
        f"Areas: {', '.join(AREA_BY_ID[a].label for a in run.areas_json or [] if a in AREA_BY_ID)}.",
        "",
    ]
    if not findings:
        out += ["Nothing is open in the areas checked.", ""]
    else:
        out.append(
            f"**{len(findings)} open**: "
            + ", ".join(f"{counts[s]} {s}" for s in SEVERITIES if counts[s])
            + ". Quickest first within each severity; effort is a guess from what the fix is."
        )
        out.append("")
    for severity in SEVERITIES:
        rows = sorted(
            (f for f in findings if f.severity == severity),
            key=lambda f: (_EFFORT_RANK[effort(f)], f.path or "", f.line or 0),
        )
        if not rows:
            continue
        out += [f"## {severity.capitalize()} ({len(rows)})", ""]
        for f in rows:
            evidence = f.evidence_json or {}
            out.append(
                f"- [ ] **{f.title}** — {_where(f)} · {effort(f)} · {f.confidence} · {label(f.rule)}"
            )
            out.append(f"  - Fix: {f.fix}")
            if evidence.get("fix_note"):
                out.append(f"  - Note: {evidence['fix_note']}")
            if evidence.get("verified"):
                out.append(f"  - Checked: {evidence['verified']}")
            if f.patch:
                out += ["", "  ```diff", *("  " + line for line in f.patch.rstrip("\n").splitlines()), "  ```"]
            out.append("")
    notes = summary.get("notes") or []
    if notes:
        out += ["## What the run said about itself", "", *(f"- {n}" for n in notes), ""]
    out += ["---", "", "Written by Codelith QA. Findings marked *suspected* or *likely* are worth reading before acting on.", ""]
    return "\n".join(out)


def sarif(run: QARun, findings: list[QAFinding]) -> dict:
    """The run as SARIF 2.1.0: one run, one rule per QA rule, one result per finding."""
    rules: dict[str, dict] = {}
    results: list[dict] = []
    for f in sorted(findings, key=lambda f: (SEVERITY_RANK.get(f.severity, 9), f.path or "", f.line or 0)):
        if f.rule not in rules:
            rules[f.rule] = {
                "id": f.rule,
                "name": label(f.rule),
                "shortDescription": {"text": label(f.rule)},
                "properties": {
                    "tags": [f.area, *(["security"] if f.area in ("security", "leakage") else [])],
                },
            }
        result: dict = {
            "ruleId": f.rule,
            "ruleIndex": list(rules).index(f.rule),
            "level": _SARIF_LEVEL.get(f.severity, "warning"),
            "message": {"text": f"{f.title}\n\n{f.message}\n\nFix: {f.fix}"},
            "partialFingerprints": {"codelithFingerprint/v1": f.fingerprint},
            "properties": {
                "severity": f.severity,
                "confidence": f.confidence,
                "area": f.area,
                "source": f.source,
                "security-severity": _SECURITY_SEVERITY.get(f.severity, "5.0"),
            },
        }
        if f.path:
            location: dict = {"artifactLocation": {"uri": f.path, "uriBaseId": "%SRCROOT%"}}
            if f.line:
                location["region"] = {"startLine": f.line, **({"endLine": f.end_line} if f.end_line else {})}
            result["locations"] = [{"physicalLocation": location}]
        results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Codelith QA",
                        "informationUri": "https://github.com/NaumanHSA/codelith",
                        "rules": list(rules.values()),
                    }
                },
                "automationDetails": {"id": f"codelith-qa/run-{run.id}"},
                "versionControlProvenance": (
                    [{"revisionId": (run.summary_json or {}).get("commit")}] if (run.summary_json or {}).get("commit") else []
                ),
                "results": results,
            }
        ],
    }


__all__ = ["effort", "markdown", "sarif"]
