"""
Secrets in the files a reading kept: in code, config, CI and images alike.

Two kinds of evidence. **Known formats** (an AWS key, a GitHub token, a private key
block) are what they look like wherever they appear. **Assignments** — a name that
says `password` or `api_key` given a literal value — are secrets only if the value
looks like one: mixed characters and enough entropy, and none of the words templates
use for placeholders. A value like `password_hash` is a column name, and `change-me`
is an invitation.

**The secret itself is never copied.** A finding records where the value is (line and
columns), and every place that shows the code masks those columns. QA would otherwise
store a second copy of the key it is warning about.

A real `.env` is kept with its values masked, so its contents cannot be checked; that
it is in the repository at all is the finding. For a local folder, an `.env` git
ignores is not in the repository, and is not reported.
"""

from __future__ import annotations

import asyncio
import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.languages import registry

AREAS = frozenset({"leakage"})
TITLE = "Secrets in code, config, CI and images"
#: Every secret format is one group: what to do is the same for each.
RULES = {"leak.env-committed": "A real .env in the repository", "leak.*": "Keys and credentials in files"}


@dataclass(frozen=True, slots=True)
class _Pattern:
    id: str
    label: str
    regex: re.Pattern
    severity: str
    #: The group holding the secret itself; 0 for the whole match.
    group: int = 0
    confidence: str = "confirmed"
    #: Judged on its value: entropy, mixed characters, no placeholder words.
    judged: bool = False


_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern("private-key", "A private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"), "critical"),
    _Pattern("aws-access-key", "An AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "critical"),
    _Pattern("github-token", "A GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"), "critical"),
    _Pattern("gitlab-token", "A GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "critical"),
    _Pattern("anthropic-key", "An Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}"), "critical"),
    _Pattern("openai-key", "An OpenAI API key", re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}"), "critical"),
    _Pattern("stripe-key", "A live Stripe key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b"), "critical"),
    _Pattern("google-api-key", "A Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "high"),
    _Pattern("slack-token", "A Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"), "high"),
    _Pattern("slack-webhook", "A Slack webhook URL", re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"), "high"),
    _Pattern(
        "jwt",
        "A signed token (JWT)",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "medium",
        confidence="likely",
    ),
    _Pattern(
        "url-password",
        "A password in a connection URL",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:([^\s@'\"/]{3,})@([^\s'\"/:]+)"),
        "high",
        group=1,
        confidence="likely",
        judged=True,
    ),
    _Pattern(
        "credential-assignment",
        "A credential written into the code",
        re.compile(
            r"(?i)\b[\w.-]*(?:password|passwd|secret|api_?key|access_?token|auth_?token|client_?secret|private_?key|signing_?key)[\w.-]*"
            r"[\"']?\s*[:=]\s*(?:[\"'])([^\"'\s]{8,})[\"']"
        ),
        "high",
        group=1,
        confidence="likely",
        judged=True,
    ),
)

#: Words templates and examples use in place of a real value.
_PLACEHOLDER = re.compile(
    r"(example|change.?me|your|xxx|placeholder|dummy|sample|fake|test|redacted|todo|replace|insert|\$\{|\{\{|<|\*\*\*|\u2022|"
    r"^password$|^secret$|^pass$|^postgres$|^root$|^admin$|^user$|^none$|^null$)",
    re.IGNORECASE,
)
#: Hosts a URL with a password points at in a development setup.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "db", "postgres", "mysql", "redis", "database", "mongo", "host.docker.internal"})
_MAX_LINE = 2000


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def looks_secret(value: str) -> bool:
    """A value that reads as a credential rather than a name, a placeholder or a path."""
    if _PLACEHOLDER.search(value) or "/" in value and value.count("/") > 1:
        return False
    classes = sum(
        bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
    )
    if re.fullmatch(r"[a-z_.]+", value) or re.fullmatch(r"[A-Z_]+", value):
        return False  # an identifier or a constant's name
    # Long and mixed, or short and very mixed: `lm-studio` is a word, `Pa55w0rd!` is not.
    return (len(value) >= 12 and classes >= 2 and _entropy(value) >= 3.2) or (classes >= 3 and _entropy(value) >= 2.8)


def _masked(value: str) -> str:
    return value[:4] + "\u2022" * 6 if len(value) > 8 else "\u2022" * 6


async def _tracked(folder: Path, path: str) -> bool:
    """Whether git tracks `path` in a local folder: an ignored `.env` is not in the repository."""

    def ask() -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", str(folder), "ls-files", "--error-unmatch", "--", path],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return True
        return result.returncode == 0

    return await asyncio.to_thread(ask)


async def run(ctx: RunContext) -> list[Finding]:
    out: list[Finding] = []
    local = next((s for s in ctx.sources if s.source_type == "local"), None)

    for f in ctx.files:
        if f.kind == "lockfile":
            continue
        if f.masked:
            name = PurePosixPath(f.path).name
            if f.kind == "env" and (local is None or await _tracked(Path(local.url_or_path).expanduser(), f.path)):
                out.append(
                    Finding(
                        rule="leak.env-committed",
                        area="leakage",
                        severity="high",
                        title=f"A real environment file, `{name}`, is in the repository",
                        message="Whoever can read the repository can read every value in it: database passwords, API "
                        "keys, signing secrets. Removing it now does not remove it from the history.",
                        fix="Rotate every secret it held, remove it from git (`git rm --cached`), add it to "
                        ".gitignore, and keep a `.env.example` with names and no values.",
                        path=f.path,
                        line=1,
                        source="check",
                    )
                )
            continue

        text = await ctx.text(f)
        provider = registry.for_path(f.path)
        in_test = bool(provider and provider.is_test_file(f.path))
        for number, line in enumerate(text.splitlines(), start=1):
            if len(line) > _MAX_LINE or not line.strip():
                continue
            taken: list[tuple[int, int]] = []
            for pattern in _PATTERNS:
                for match in pattern.regex.finditer(line):
                    start, end = match.span(pattern.group)
                    if any(start < b and end > a for a, b in taken):
                        continue
                    value = match.group(pattern.group)
                    if pattern.judged and not looks_secret(value):
                        continue
                    if pattern.id == "url-password" and match.group(2).lower() in _LOCAL_HOSTS:
                        continue
                    taken.append((start, end))
                    severity = pattern.severity
                    note = ""
                    if in_test:
                        severity, note = "low", " It is in a test, where keys are usually fakes; check this one is."
                    elif f.kind == "env":
                        note = " It is in an environment template, which people copy and fill in: the value is public."
                    out.append(
                        Finding(
                            rule=f"leak.{pattern.id}",
                            area="leakage",
                            severity=severity,
                            title=f"{pattern.label} in `{PurePosixPath(f.path).name}`",
                            message="Anyone who can read the repository can use it, and it stays in the history "
                            "after the line is deleted." + note,
                            fix="Revoke and rotate it, then read it from the environment or a secret store instead.",
                            path=f.path,
                            line=number,
                            confidence=pattern.confidence,
                            source="check",
                            evidence={"masks": [[number, start, end]], "shown": _masked(value), "kind": pattern.id},
                        )
                    )
        await ctx.checkpoint()
    return out


__all__ = ["AREAS", "TITLE", "looks_secret", "run"]
