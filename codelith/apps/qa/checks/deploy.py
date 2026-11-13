"""
How the code is built and shipped: Dockerfiles, compose files and CI workflows.

The same in every language, so it lives here rather than in a provider. Each check
reads one kept project file and points at the line that says it.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import yaml

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding

AREAS = frozenset({"config", "leakage", "security"})
TITLE = "Containers, compose files and CI workflows"
RULES = {
    "config.docker-unpinned-image": "Container images not pinned",
    "config.docker-copies-everything": "`COPY .` with no .dockerignore",
    "config.docker-root": "Containers running as root",
    "leak.docker-secret": "Secrets baked into images",
    "security.docker-pipe-to-shell": "Downloaded scripts run unchecked",
    "config.compose-database-published": "Databases published on every interface",
    "leak.compose-placeholder-secret": "Placeholder secrets in compose",
    "leak.compose-secret": "Secrets written into compose",
    "security.compose-privileged": "Privileged containers",
    "security.compose-docker-socket": "The Docker socket mounted",
    "config.ci-action-unpinned": "CI actions not pinned to a commit",
    "security.ci-script-injection": "Script injection in CI",
    "leak.ci-secret-echoed": "Secrets echoed in CI",
    "security.ci-pr-target-checkout": "Pull request code run with secrets",
}

_SECRET_NAME = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIAL)", re.IGNORECASE)
_DATASTORES = ("postgres", "mysql", "mariadb", "redis", "mongo", "elasticsearch", "opensearch", "rabbitmq", "memcached", "neo4j", "clickhouse", "minio")
_FIRST_PARTY_ACTIONS = ("actions/", "github/")
_PLACEHOLDER = re.compile(r"(change.?me|example|placeholder|dummy|your|xxx|replace|todo|secret$|password$)", re.IGNORECASE)
_UNTRUSTED_CONTEXT = re.compile(
    r"\$\{\{\s*github\.(?:event\.(?:issue|pull_request|comment|review|review_comment|discussion|pages|head_commit|commits|workflow_run)"
    r"[^}]*\.(?:title|body|message|name|label|ref|head_ref|email)|head_ref)\s*\}\}"
)


def _line(lines: list[str], needle: str, after: int = 0) -> int | None:
    for i in range(after, len(lines)):
        if needle in lines[i]:
            return i + 1
    return None


def _finding(rule: str, area: str, severity: str, title: str, message: str, fix: str, path: str, line: int | None, **kw) -> Finding:
    return Finding(rule=rule, area=area, severity=severity, title=title, message=message, fix=fix, path=path, line=line, source="check", **kw)


def _dockerfile(path: str, text: str, siblings: set[str], areas: frozenset[str]) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()
    joined = re.sub(r"\\\s*\n", " ", text).splitlines()
    stages: list[str] = []
    last_from = 0
    user = False
    for number, raw in enumerate(lines, start=1):
        words = raw.strip().split()
        if not words or words[0].startswith("#"):
            continue
        op = words[0].upper()
        if op == "FROM" and len(words) > 1:
            image = words[1]
            last_from, user = number, False
            if len(words) >= 4 and words[2].upper() == "AS":
                stages.append(words[3])
            base = image.split("@", 1)[0]
            tag = base.rsplit(":", 1)[1] if ":" in base.rsplit("/", 1)[-1] else ""
            if "config" in areas and image not in stages and image != "scratch" and "@sha256:" not in image and tag in ("", "latest") and "$" not in image:
                out.append(
                    _finding(
                        "config.docker-unpinned-image",
                        "config",
                        "low",
                        f"The image `{image}` is not pinned to a version",
                        "Without a tag, every build takes whatever `latest` is that day: the same Dockerfile builds a "
                        "different image next month, and a breaking release arrives unannounced.",
                        "Name the version (`python:3.12-slim`), or pin the digest for repeatable builds.",
                        path,
                        number,
                    )
                )
        elif op == "USER":
            user = len(words) > 1 and words[1] not in ("root", "0", "0:0")
        elif op in ("COPY", "ADD") and "config" in areas and len(words) >= 3 and words[1] in (".", "./") and ".dockerignore" not in siblings:
            out.append(
                _finding(
                    "config.docker-copies-everything",
                    "config",
                    "medium",
                    "`COPY .` with no `.dockerignore`",
                    "Everything in the folder goes into the image: `.env`, `.git` with its whole history, local "
                    "databases, caches. Anyone who can pull the image can read them.",
                    "Add a `.dockerignore` listing `.env*`, `.git`, caches and build output.",
                    path,
                    number,
                )
            )
    for number, raw in enumerate(joined, start=1):
        words = raw.strip().split()
        if not words:
            continue
        op = words[0].upper()
        if op in ("ENV", "ARG") and len(words) > 1 and "leakage" in areas:
            pairs = [w.split("=", 1) for w in words[1:] if "=" in w] or ([[words[1], " ".join(words[2:])]] if op == "ENV" and len(words) > 2 else [])
            for name, value in pairs:
                value = value.strip("'\"")
                if _SECRET_NAME.search(name) and value and not value.startswith("$"):
                    at = _line(lines, name) or number
                    col = lines[at - 1].find(value) if at <= len(lines) else -1
                    out.append(
                        _finding(
                            "leak.docker-secret",
                            "leakage",
                            "high",
                            f"`{name}` is set in the Dockerfile",
                            "A value set with ENV or ARG is baked into the image's layers: anyone who can pull the "
                            "image can read it with `docker history`.",
                            "Pass it at run time (`docker run -e`, a compose `env_file`, or a secret mount).",
                            path,
                            at,
                            evidence={"masks": [[at, col, col + len(value)]] if col >= 0 else []},
                        )
                    )
        if "security" in areas and re.search(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash)\b", raw):
            out.append(
                _finding(
                    "security.docker-pipe-to-shell",
                    "security",
                    "medium",
                    "A script is downloaded and run in one step",
                    "Whatever the URL serves on build day runs as root in the image, unchecked.",
                    "Download it, check its checksum, then run it; or install the package from the distribution.",
                    path,
                    number,
                )
            )
    if "config" in areas and last_from and not user:
        out.append(
            _finding(
                "config.docker-root",
                "config",
                "medium",
                "The container runs as root",
                "No `USER` follows the last `FROM`, so the process runs as root: a bug that lets someone run code "
                "in it hands them root in the container, one step from the host.",
                "Create a user and switch to it before the `CMD`: `RUN useradd -r app` then `USER app`.",
                path,
                last_from,
            )
        )
    return out


def _compose(path: str, text: str, areas: frozenset[str]) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return out
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, dict):
        return out
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        start = (_line(lines, f"{name}:") or 1) - 1
        image = str(service.get("image") or "").lower()
        if "config" in areas and any(d in image for d in _DATASTORES):
            for port in service.get("ports") or []:
                spec = str(port)
                if ":" in spec and not spec.startswith(("127.0.0.1", "localhost", "[::1]")):
                    out.append(
                        _finding(
                            "config.compose-database-published",
                            "config",
                            "medium",
                            f"`{name}` is published on every interface",
                            f"`{spec}` opens the {image.split(':', 1)[0]} port to every machine that can reach this "
                            "host, not only to the app. A database answering the network with a default password is "
                            "found within hours.",
                            "Bind it to the host only (`127.0.0.1:" + spec.split(":")[-1] + "`), or drop `ports` and let "
                            "services reach it over the compose network.",
                            path,
                            _line(lines, spec, start) or start + 1,
                        )
                    )
        env = service.get("environment")
        pairs = list(env.items()) if isinstance(env, dict) else [tuple(str(e).split("=", 1)) if "=" in str(e) else (str(e), None) for e in env or []]
        if "leakage" in areas:
            for key, value in pairs:
                value = "" if value is None else str(value)
                if _SECRET_NAME.search(str(key)) and value and "${" not in value:
                    placeholder = bool(_PLACEHOLDER.search(value))
                    out.append(
                        _finding(
                            "leak.compose-placeholder-secret" if placeholder else "leak.compose-secret",
                            "leakage",
                            "medium",
                            f"`{key}` defaults to a placeholder in the compose file"
                            if placeholder
                            else f"`{key}` is written into the compose file",
                            (
                                "If nobody overrides it, the app runs with a key anyone who reads the repository "
                                "knows: whatever it signs or encrypts can be forged or read."
                                if placeholder
                                else "Fine for a throwaway local database; a compose file used anywhere else hands "
                                "the value to everyone who can read the repository."
                            ),
                            f"Read it from the environment with no default (`{key}: ${{{key}:?set {key}}}`), so the "
                            "stack refuses to start without a real value.",
                            path,
                            _line(lines, str(key), start) or start + 1,
                        )
                    )
        if "security" in areas:
            if service.get("privileged") is True:
                out.append(
                    _finding(
                        "security.compose-privileged",
                        "security",
                        "high",
                        f"`{name}` runs privileged",
                        "A privileged container can reach the host's devices and kernel: escaping it is a matter of "
                        "minutes.",
                        "Remove `privileged`; grant the one capability it needs with `cap_add`.",
                        path,
                        _line(lines, "privileged", start) or start + 1,
                    )
                )
            for volume in service.get("volumes") or []:
                if "docker.sock" in str(volume):
                    out.append(
                        _finding(
                            "security.compose-docker-socket",
                            "security",
                            "high",
                            f"`{name}` mounts the Docker socket",
                            "Whoever controls the Docker socket controls the host: the container can start a privileged "
                            "container of its own.",
                            "Drop the mount, or put a proxy in front that allows only the calls it needs.",
                            path,
                            _line(lines, "docker.sock", start) or start + 1,
                        )
                    )
    return out


def _workflow(path: str, text: str, areas: frozenset[str]) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()
    pr_target = bool(re.search(r"^\s*pull_request_target\s*:|on:\s*\[?[^\n]*pull_request_target", text, re.MULTILINE))
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        use = re.match(r"-?\s*uses:\s*([\w.-]+/[\w./-]+)@([\w./-]+)", line)
        if use and "config" in areas:
            action, ref = use.groups()
            if not action.startswith(_FIRST_PARTY_ACTIONS) and not re.fullmatch(r"[0-9a-f]{40}", ref):
                out.append(
                    _finding(
                        "config.ci-action-unpinned",
                        "config",
                        "low",
                        f"`{action}@{ref}` is not pinned to a commit",
                        "A tag can be moved: whoever controls that action can change what runs in your pipeline, "
                        "with its secrets, without a change on your side.",
                        "Pin it to the commit the tag points at (`@<40-character sha>  # v4`).",
                        path,
                        number,
                    )
                )
        if "security" in areas and _UNTRUSTED_CONTEXT.search(raw):
            out.append(
                _finding(
                    "security.ci-script-injection",
                    "security",
                    "high",
                    "Text someone else wrote is put straight into a script",
                    "A pull request title or comment containing `\"; curl ... | sh` runs in the workflow, with its "
                    "token and secrets.",
                    "Pass it through an environment variable (`env: TITLE: ${{ ... }}`) and use `\"$TITLE\"` in the script.",
                    path,
                    number,
                )
            )
        if "leakage" in areas and re.search(r"\becho\b[^\n]*\$\{\{\s*secrets\.", raw):
            out.append(
                _finding(
                    "leak.ci-secret-echoed",
                    "leakage",
                    "high",
                    "A secret is echoed in the workflow",
                    "Masking in the log is best effort: a secret that is transformed, split or encoded on the way out "
                    "is printed in the clear for everyone who can read the run.",
                    "Do not print it; pass it to the step that needs it through `env:`.",
                    path,
                    number,
                )
            )
        if pr_target and "security" in areas and re.search(r"ref:\s*\$\{\{\s*github\.event\.pull_request\.head\.(sha|ref)", raw):
            out.append(
                _finding(
                    "security.ci-pr-target-checkout",
                    "security",
                    "high",
                    "`pull_request_target` checks out the pull request's code",
                    "That trigger runs with the repository's secrets and a write token; checking out the contributor's "
                    "code and running it hands both to anyone who opens a pull request.",
                    "Use `pull_request` for anything that runs the contributor's code.",
                    path,
                    number,
                )
            )
    return out


async def run(ctx: RunContext) -> list[Finding]:
    out: list[Finding] = []
    folders: dict[str, set[str]] = {}
    for f in ctx.all_files:
        folders.setdefault(str(PurePosixPath(f.path).parent), set()).add(PurePosixPath(f.path).name)
    for f in ctx.files:
        if f.kind not in ("deploy", "ci"):
            continue
        name = PurePosixPath(f.path).name.lower()
        text = await ctx.text(f)
        if f.kind == "deploy" and "dockerfile" in name and name != ".dockerignore":
            out += _dockerfile(f.path, text, folders.get(str(PurePosixPath(f.path).parent), set()), ctx.areas)
        elif f.kind == "deploy" and name.startswith(("docker-compose", "compose")):
            out += _compose(f.path, text, ctx.areas)
        elif f.kind == "ci" and name.endswith((".yml", ".yaml")):
            out += _workflow(f.path, text, ctx.areas)
    return [f for f in out if f.area in ctx.areas]


__all__ = ["AREAS", "TITLE", "run"]
