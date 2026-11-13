"""What a QA run can be asked to look at, and how deep."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Area:
    id: str
    label: str
    #: One line for the picker.
    blurb: str
    #: What it looks for, as a short list for the picker's detail.
    looks_for: tuple[str, ...]
    icon: str


AREAS: tuple[Area, ...] = (
    Area(
        "security",
        "Security",
        "Ways in for an attacker: injection, unsafe loading, checks turned off.",
        (
            "SQL, shell and code built from values",
            "unsafe deserialisation (pickle, yaml.load)",
            "TLS or JWT checks turned off",
            "weak hashing or `random` for secrets",
            "CORS open to every origin, debug left on",
            "routes that reach data with no auth step",
            "request data reaching SQL, a shell, a file path or an outbound URL",
        ),
        "shield-alert",
    ),
    Area(
        "leakage",
        "Data leakage",
        "Secrets and private data where they should not be.",
        (
            "keys, tokens and passwords in code, config, CI and images",
            "a committed .env",
            "credentials written to logs",
            "exception text sent to clients",
            "password hashes and secrets in response models",
            "request data written to logs",
        ),
        "key-round",
    ),
    Area(
        "dependencies",
        "Dependencies & compatibility",
        "What the code relies on, and whether it fits together.",
        (
            "imported but not declared, or relied on only through another package",
            "development-only packages in shipped code; declared and never imported",
            "unpinned with no lockfile; lockfile and manifest disagreeing",
            "syntax newer than the declared Python; images older than the code needs",
            "online, if you allow it: known vulnerabilities, how far behind, licences",
        ),
        "package",
    ),
    Area(
        "errors",
        "Error handling",
        "Failures that disappear, or wait forever.",
        (
            "exceptions caught and dropped",
            "bare except, empty catch, ignored errors",
            "network calls with no timeout",
            "errors re-raised without their cause",
        ),
        "triangle-alert",
    ),
    Area(
        "breaks",
        "Things that will break",
        "Code that works until the day it does not.",
        (
            "mutable default arguments",
            "`is` compared with a literal",
            "environment variables the code needs that nothing declares",
        ),
        "bug",
    ),
    Area(
        "performance",
        "Performance & concurrency",
        "Work that holds everything else up.",
        ("blocking calls inside async code: sleep, requests, subprocess",),
        "gauge",
    ),
    Area(
        "config",
        "Configuration & deployment",
        "The files that build and ship it: containers, compose, CI.",
        (
            "a container that runs as root, unpinned or `latest` images",
            "no .dockerignore, so `COPY .` takes everything",
            "databases published on every interface, passwords in compose",
            "CI actions not pinned, script injection, secrets echoed",
        ),
        "container",
    ),
    Area(
        "tests",
        "Tests",
        "What nothing checks, and tests that check nothing.",
        (
            "routes and commands no test reaches, ranked by what they touch",
            "tests that assert nothing",
        ),
        "flask-conical",
    ),
)

AREA_IDS: tuple[str, ...] = tuple(a.id for a in AREAS)
AREA_BY_ID = {a.id: a for a in AREAS}

#: Most severe first.
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}


@dataclass(frozen=True, slots=True)
class Depth:
    id: str
    label: str
    blurb: str
    #: False until the phase that builds it lands; the picker says so.
    available: bool
    why_not: str = ""


DEPTHS: tuple[Depth, ...] = (
    Depth("quick", "Quick", "Rules and checks over every file. No model; seconds.", True),
    Depth(
        "thorough",
        "Thorough",
        "Adds the model's review of the riskiest functions, each claim checked against the line it "
        "quotes and by a second call. Minutes, and it uses the quality model.",
        True,
    ),
    Depth(
        "tests",
        "Run tests",
        "Adds the sandbox: a clean install and the codebase's own tests and tools (ruff, mypy, "
        "tsc, go vet), run in Docker with no network and none of your keys. Needs Docker running; "
        "the install may take minutes.",
        True,
    ),
)

__all__ = ["AREAS", "AREA_BY_ID", "AREA_IDS", "DEPTHS", "SEVERITIES", "SEVERITY_RANK", "Area", "Depth"]
