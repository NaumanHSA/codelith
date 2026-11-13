"""
What each command does.

Kept in one module because they are small and they share a shape: resolve what the
user meant, make one or two API calls, print for a person or for a pipe. The moment
one of these needs its own file it has probably grown a second responsibility.
"""

from __future__ import annotations

import getpass
import re
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from rich.table import Table

from codelith.cli.client import ApiClient, CliError, Credentials
from codelith.cli.render import Output, humanise_seconds, out

TERMINAL = {"completed", "failed", "cancelled"}

#: How often to ask the server how a job is going. Analysis is minutes of model time;
#: a tighter loop buys nothing and fills the log.
POLL_SECONDS = 3.0


# ── source resolution ─────────────────────────────────────────────────────────

_HOSTS = {"github.com": "github", "gitlab.com": "gitlab", "bitbucket.org": "bitbucket"}


def resolve_source(target: str) -> tuple[str, str, str]:
    """
    Work out what the user pointed at: `(source_type, url_or_path, name)`.

    A bare `github.com/acme/repo` is what the landing page has always advertised, so
    it has to work without a scheme. Anything that exists on disk is local, checked
    first — a directory called `gitlab.com` is a directory.
    """
    path = Path(target).expanduser()
    if path.exists():
        resolved = path.resolve()
        return "local", str(resolved), resolved.name

    candidate = target if "://" in target else f"https://{target}"
    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    source_type = _HOSTS.get(host)
    if not source_type:
        raise CliError(
            f"Cannot tell what {target!r} is.\n"
            "Give a path that exists, or a GitHub, GitLab or Bitbucket URL."
        )

    slug = parsed.path.strip("/").removesuffix(".git")
    if not slug or "/" not in slug:
        raise CliError(f"{target!r} does not look like a repository — expected owner/name.")
    return source_type, candidate, slug.split("/")[-1]


def _find_project(api: ApiClient, name_or_id: str | None) -> dict:
    """
    The project a command should act on.

    With one analysed codebase, naming it every time is friction for no benefit — so
    it is optional, and only ambiguous when there is genuine ambiguity.
    """
    projects = api.projects()
    if not projects:
        raise CliError("Nothing analysed yet. Run `codelith analyse <path or url>` first.")

    if name_or_id is None:
        if len(projects) == 1:
            return projects[0]
        names = ", ".join(p["name"] for p in projects)
        raise CliError(f"Which codebase? Pass --project. One of: {names}")

    if name_or_id.isdigit():
        for p in projects:
            if p["id"] == int(name_or_id):
                return p
    matches = [p for p in projects if p["name"].lower() == name_or_id.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CliError(f"No codebase called {name_or_id!r}.")
    raise CliError(f"{name_or_id!r} matches more than one codebase — use its id.")


# ── commands ──────────────────────────────────────────────────────────────────


def cmd_login(args, o: Output) -> int:
    creds = Credentials.load()
    if args.api_url:
        creds.api_url = args.api_url.rstrip("/")

    email = args.email or input("Email: ").strip()
    password = args.password or getpass.getpass("Password: ")

    api = ApiClient(Credentials(api_url=creds.api_url))
    token = api.login(email, password)
    creds.token = token
    creds.save()

    o.say(f"[green]Signed in[/green] to {creds.api_url} as {email}")
    o.result({"api_url": creds.api_url, "email": email})
    return 0


def cmd_status(args, o: Output) -> int:
    api = ApiClient()
    projects = api.projects()

    if not projects:
        o.say("Nothing analysed yet. Run [bold]codelith analyse .[/bold] to start.")
        o.result([])
        return 0

    o.result(projects)
    if o.as_json:
        return 0

    table = Table(box=None, pad_edge=False, header_style="dim")
    for col in ("id", "codebase", "knowledge base", "commit", "pages", "source"):
        table.add_column(col)
    for p in projects:
        src = (p.get("sources") or [{}])[0]
        probe = (src.get("config_json") or {}).get("probe") or {}
        table.add_row(
            str(p["id"]),
            p["name"],
            _kb_label(p.get("kb_status")),
            (probe.get("commit_sha") or "")[:7] or "—",
            str((p.get("stats") or {}).get("page_count", 0)),
            src.get("url_or_path", "—"),
        )
    out.print(table)
    return 0


def _kb_label(status: str | None) -> str:
    return {
        "ready": "[green]ready[/green]",
        "degraded": "[yellow]degraded[/yellow]",
        "building": "[cyan]building[/cyan]",
        "failed": "[red]failed[/red]",
    }.get(status or "", "[dim]not analysed[/dim]")


def _same_place(a: str, b: str, source_type: str) -> bool:
    """Whether two spellings of a source name the same repository."""
    if source_type == "local":
        import os

        def norm(x: str) -> str:
            return os.path.normcase(os.path.realpath(os.path.expanduser(x)))

        return norm(a) == norm(b)

    def bare(u: str) -> str:
        u = u.strip().lower()
        u = re.sub(r"^[a-z]+://", "", u).removeprefix("www.")
        return u.rstrip("/").removesuffix(".git")

    return bare(a) == bare(b)


def find_codebase(projects: list[dict], source_type: str, url_or_path: str, branch: str | None) -> dict | None:
    """
    The codebase already reading this source, if there is one.

    `analyse` used to create a new codebase every time it ran, so reading the same
    folder twice left two codebases, two histories, and a second reading that could
    keep nothing from the first. Now the second run finds the first.
    """
    for p in projects:
        for src in p.get("sources") or []:
            if (
                src.get("source_type") == source_type
                and _same_place(src.get("url_or_path") or "", url_or_path, source_type)
                and (src.get("branch") or None) == (branch or None)
            ):
                return p
    return None


def _codebase_for(api: ApiClient, target: str, name: str | None, branch: str | None, o: Output) -> dict:
    source_type, url_or_path, default_name = resolve_source(target)
    existing = find_codebase(api.projects(), source_type, url_or_path, branch)
    if existing is not None:
        o.step(f"[dim]Codebase[/dim] #{existing['id']} {existing['name']} [dim]already reads this[/dim]")
        return existing
    name = name or default_name
    o.step(f"[dim]Reading[/dim] {url_or_path} [dim]as[/dim] {name}")
    project = api.create_with_source(name, source_type, url_or_path, branch)
    o.step(f"[dim]Codebase[/dim] #{project['id']} [dim]created[/dim]")
    return project


def cmd_analyse(args, o: Output) -> int:
    api = ApiClient()
    project = _codebase_for(api, args.target, args.name, args.branch, o)

    force = bool(getattr(args, "from_scratch", False))
    job = api.analyse(project["id"], force=force)
    o.step(
        f"[dim]Analysis job[/dim] #{job['id']} [dim]started"
        + (", reading everything from scratch" if force else ", keeping what did not change")
        + "[/dim]"
    )

    final = _follow(api, job["id"], o) if not args.no_wait else job
    if args.no_wait:
        o.say("Started. Follow it with [bold]codelith status[/bold] or the studio.")
        o.result({"project": project, "job": job})
        return 0

    if final["status"] != "completed":
        o.fail(f"Analysis {final['status']}: {final.get('error_message') or 'no reason given'}")
        o.result({"project": project, "job": final})
        return 1

    kb = api.knowledge_base(project["id"])
    o.say(
        f"[green]Read[/green] {project['name']} — "
        f"{kb.get('module_count', 0)} modules, {kb.get('entity_count', 0)} facts, "
        f"commit {(kb.get('knowledge_base') or {}).get('commit_sha', '')[:7]}"
    )
    if kept := describe_reuse(kb):
        o.say(f"[dim]{kept}[/dim]")
    o.say("Ask it something: [bold]codelith ask \"how does auth work?\"[/bold]")
    o.result({"project": project, "job": final, "knowledge_base": kb})
    return 0


def _follow(api: ApiClient, job_id: int, o: Output) -> dict:
    """
    Poll until the job stops, narrating each stage as it changes.

    Stage names come from the job's own steps rather than a list kept here — the
    studio already has that table, and a second copy in the CLI would be the one that
    goes stale.
    """
    seen: set[str] = set()
    started = time.monotonic()
    while True:
        job = api.job(job_id)
        for step in job.get("steps") or []:
            # `JobStepOut` serialises `agent_name` under the alias `name`, which is
            # what the studio reads. Accept either, so the CLI does not break if the
            # alias moves — and so it works against an older server.
            agent = step.get("name") or step.get("agent_name") or "?"
            key = f"{agent}:{step['status']}"
            if step["status"] in ("running", "completed") and key not in seen:
                seen.add(key)
                if step["status"] == "running":
                    o.step(f"  [cyan]▸[/cyan] {_pretty(agent)}")
        if job["status"] in TERMINAL:
            o.step(f"[dim]Finished in {humanise_seconds(time.monotonic() - started)}[/dim]")
            return job
        time.sleep(POLL_SECONDS)


def describe_reuse(kb: dict | None) -> str | None:
    """What the last reading kept from the one before, in a sentence. None when it kept
    nothing or the server is too old to say."""
    stats = ((kb or {}).get("knowledge_base") or {}).get("stats") or {}
    reuse = stats.get("reuse") or {}
    if not reuse.get("from_kb"):
        return None
    changed = sum(reuse.get(k, 0) for k in ("files_changed", "files_added", "files_removed"))
    parts = [f"{changed} file{'s' if changed != 1 else ''} changed"]
    if reuse.get("vectors_copied") is not None:
        parts.append(f"kept {reuse['vectors_copied']} vectors, embedded {reuse.get('vectors_embedded', 0)}")
    if reuse.get("summaries_kept") is not None:
        parts.append(f"kept {reuse['summaries_kept']} summaries, wrote {reuse.get('summaries_written', 0)}")
    if reuse.get("narratives_kept"):
        parts.append(f"kept {reuse['narratives_kept']} narratives")
    if reuse.get("architecture_kept"):
        parts.append("kept the architecture")
    return "; ".join(parts)


# ── read every commit ─────────────────────────────────────────────────────────


def git_root(path: Path) -> Path | None:
    """The top of the git repository `path` is in, or None."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out.stdout.strip()).resolve()


def git_head(root: Path) -> str | None:
    import subprocess

    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


class Watch:
    """
    One check of `codelith watch`, kept apart from the loop so the rules can be tested
    without one: read when `HEAD` is a commit no reading has seen, one reading at a
    time, and when one finishes, read whatever `HEAD` is by then — a burst of commits
    costs one reading, not one each.
    """

    def __init__(self, api: ApiClient, project: dict, o: Output) -> None:
        self.api = api
        self.project = project
        self.o = o
        self.job_id: int | None = None
        self.started_at = 0.0
        self.handled: str | None = None

    def step(self, head: str | None) -> None:
        if self.job_id is not None:
            job = self.api.job(self.job_id)
            if job["status"] not in TERMINAL:
                return
            self._report(job)
            self.job_id = None
        if not head or head == self.handled:
            return
        kb = self.api.knowledge_base(self.project["id"])
        read_at = ((kb or {}).get("knowledge_base") or {}).get("commit_sha")
        if read_at == head:
            if self.handled is None:
                self.o.say(f"[green]Up to date[/green] at {head[:8]}")
            self.handled = head
            return
        latest = (self.api.project(self.project["id"]).get("latest_job") or {}).get("status")
        if latest in ("pending", "running"):
            return  # someone else is reading it; look again when that is done
        job = self.api.analyse(self.project["id"])
        self.job_id = job["id"]
        self.started_at = time.monotonic()
        self.handled = head
        self.o.say(f"[cyan]{head[:8]}[/cyan] [dim]reading the changes (job #{job['id']})…[/dim]")

    def _report(self, job: dict) -> None:
        took = humanise_seconds(time.monotonic() - self.started_at)
        if job["status"] != "completed":
            self.o.fail(f"  Reading {job['status']} after {took}: {job.get('error_message') or 'no reason given'}")
            return
        kept = describe_reuse(self.api.knowledge_base(self.project["id"]))
        self.o.say(f"  [green]Read[/green] in {took}" + (f" [dim]— {kept}[/dim]" if kept else ""))


def cmd_watch(args, o: Output) -> int:
    root = git_root(Path(args.target).expanduser().resolve())
    if root is None:
        raise CliError(f"{args.target} is not inside a git repository. Watching reads each new commit.")
    api = ApiClient()
    project = _codebase_for(api, str(root), args.name, None, o)
    o.say(f"Watching {root} — every commit is read again. Ctrl+C to stop.")
    watch = Watch(api, project, o)
    while True:
        watch.step(git_head(root))
        time.sleep(max(1.0, args.interval))


def origin_url(root: Path) -> str | None:
    """The checkout's `origin`, as an https URL: `git@github.com:o/r.git` → `https://github.com/o/r`."""
    import subprocess

    try:
        url = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if m := re.match(r"^[\w.-]+@([^:]+):(.+)$", url):
        url = f"https://{m.group(1)}/{m.group(2)}"
    return url or None


def codebase_for_checkout(projects: list[dict], root: Path) -> tuple[dict, Path] | None:
    """
    The codebase a checkout belongs to, and the folder its paths are relative to.

    The folder itself first — a codebase read from this very directory. Then the
    checkout's `origin`: a clone of a repository read from GitHub is that codebase, and
    its paths are relative to the clone's top, which is how they were read.
    """
    if (hit := find_codebase(projects, "local", str(root), None)) is not None:
        return hit, root
    url = origin_url(root)
    if url:
        try:
            kind, normalised, _ = resolve_source(url)
        except CliError:
            return None
        for branch in (None, *{(s.get("branch")) for p in projects for s in (p.get("sources") or [])}):
            if (hit := find_codebase(projects, kind, normalised, branch)) is not None:
                return hit, root
    return None


def cmd_review(args, o: Output) -> int:
    from codelith.knowledge import changes as change_io

    folder = Path(args.target).expanduser().resolve()
    root = git_root(folder)
    if root is None:
        raise CliError(f"{args.target} is not inside a git repository. Review reads a change from git.")

    api = ApiClient()
    if args.project:
        project, base_dir = _find_project(api, args.project), root
    else:
        found = codebase_for_checkout(api.projects(), root)
        if found is None:
            raise CliError(
                "No codebase reads this repository yet, so there is nothing to check a change against.\n"
                "Read it first: codelith analyse ."
            )
        project, base_dir = found

    kb = api.knowledge_base(project["id"])
    commit = ((kb or {}).get("knowledge_base") or {}).get("commit_sha")
    if not kb or not commit:
        raise CliError(f"{project['name']} has not been analysed yet. Run: codelith analyse .")

    base = args.against
    if not base:
        if change_io.has_commit(root, commit):
            base = commit
        else:
            base = "HEAD"
            o.warn(
                f"The knowledge was read at {commit[:8]}, which this checkout does not have; "
                "comparing with HEAD instead."
            )
    try:
        change = change_io.collect(base_dir, base, args.head)
    except change_io.ChangeError as exc:
        raise CliError(str(exc)) from exc

    if not change.files:
        o.say(f"Nothing has changed against {base[:8]}.")
        o.result({"project": project["name"], "base": base, "verdict": "clear", "files": 0})
        return 0

    o.step(
        f"[dim]Reviewing[/dim] {len(change.files)} changed file(s) [dim]in[/dim] {project['name']} "
        f"[dim]against[/dim] {base[:8]}"
    )
    result = api.review(project["id"], change.to_dict())
    report = result.get("report") or {}
    o.result(result)
    if not o.as_json:
        colour = {"stop": "red", "check": "yellow", "clear": "green"}.get(result.get("verdict"), "white")
        out.print(f"\n[bold {colour}]{(result.get('verdict') or '').upper()}[/bold {colour}]  ", end="")
        brief = report.get("brief") or result.get("summary") or ""
        for line in brief.splitlines():
            if line in ("Stop and look:",):
                out.print(f"[bold red]{line}[/bold red]")
            elif line in ("Check:",):
                out.print(f"[bold yellow]{line}[/bold yellow]")
            elif line.endswith(":") and not line.startswith(" "):
                out.print(f"[bold]{line}[/bold]")
            else:
                out.print(line, markup=False, highlight=False)
        out.print(f"[dim]Kept as review #{result.get('id')}: the codebase's Review page in the studio shows it.[/dim]")
    # 1 is "the command ran and the answer was no": something to stop for.
    return 1 if result.get("verdict") == "stop" else 0


_SEVERITIES = ("critical", "high", "medium", "low", "info")


def gate(by_severity: dict, fail_on: str) -> int:
    """How many open findings are at `fail_on` or worse. `never` fails on nothing."""
    if fail_on == "never":
        return 0
    worst = _SEVERITIES.index(fail_on)
    return sum(int(by_severity.get(s) or 0) for s in _SEVERITIES[: worst + 1])


def cmd_qa(args, o: Output) -> int:
    """
    Run QA on the codebase's latest reading and wait for it. Exit 1 when something at
    `--fail-on` or worse is open (a CI gate), 0 when not; a run that fails or is
    cancelled is an error. Findings dismissed or accepted in the studio do not count.
    """
    import time

    api = ApiClient()
    if args.project:
        project = _find_project(api, args.project)
    else:
        root = git_root(Path(args.target).expanduser().resolve())
        found = codebase_for_checkout(api.projects(), root) if root is not None else None
        if found is None:
            raise CliError(
                "No codebase reads this folder yet, so there is nothing to check.\n"
                "Read it first (codelith analyse .), or name one with --project."
            )
        project = found[0]

    catalog = api.qa_catalog(project["id"])
    known = [a["id"] for a in catalog.get("areas") or []]
    areas = [a.strip() for a in (args.areas or "").split(",") if a.strip()] or known
    unknown = [a for a in areas if a not in known]
    if unknown:
        raise CliError(f"Unknown area(s): {', '.join(unknown)}. Choose from: {', '.join(known)}.")

    run = api.qa_start(
        project["id"],
        {"areas": areas, "depth": args.depth, "online": bool(args.online), "scope": {"kind": "all"}},
    )
    o.step(f"[dim]QA run[/dim] #{run['id']} [dim]on[/dim] {project['name']} [dim]—[/dim] {', '.join(areas)} [dim]({args.depth})[/dim]")
    try:
        while run.get("status") in ("queued", "running"):
            time.sleep(2)
            run = api.qa_run(project["id"], run["id"])
    except KeyboardInterrupt:
        api.qa_cancel(project["id"], run["id"])
        raise

    if run.get("status") != "completed":
        raise CliError(f"QA run #{run['id']} {run.get('status')}: {run.get('error') or 'no reason given'}")

    summary = run.get("summary") or {}
    by_severity = summary.get("by_severity") or {}
    if args.sarif:
        Path(args.sarif).write_text(api.qa_report(project["id"], run["id"], "sarif"), encoding="utf-8")
        o.step(f"[dim]SARIF written to[/dim] {args.sarif}")
    if args.markdown:
        Path(args.markdown).write_text(api.qa_report(project["id"], run["id"], "markdown"), encoding="utf-8")
        o.step(f"[dim]Fix plan written to[/dim] {args.markdown}")

    failing = gate(by_severity, args.fail_on)
    o.result({
        "project": project["name"],
        "run": run["id"],
        "open": summary.get("open", 0),
        "by_severity": by_severity,
        "new": summary.get("new", 0),
        "fixed": summary.get("fixed", 0),
        "fail_on": args.fail_on,
        "failing": failing,
        "notes": summary.get("notes") or [],
    })
    if not o.as_json:
        counts = ", ".join(f"{by_severity.get(s, 0)} {s}" for s in _SEVERITIES if by_severity.get(s))
        out.print(f"\n{summary.get('open', 0)} open" + (f" ({counts})" if counts else "") + f" in {summary.get('files', 0)} files.")
        if summary.get("compared_with"):
            out.print(f"[dim]{summary.get('new', 0)} new and {summary.get('fixed', 0)} fixed since run #{summary['compared_with']}.[/dim]")
        for note in summary.get("notes") or []:
            out.print(f"[dim]· {note}[/dim]", highlight=False)
        if failing:
            out.print(f"[bold red]FAIL[/bold red]  {failing} open at {args.fail_on} or worse.")
        else:
            out.print(f"[bold green]PASS[/bold green]  nothing open at {args.fail_on} or worse." if args.fail_on != "never" else "")
    return 1 if failing else 0


def cmd_agents_md(args, o: Output) -> int:
    """
    The instruction file agents read first, from the reading: printed, or with
    `--write` put into AGENTS.md / CLAUDE.md, replacing only the section it wrote
    before so anything written by hand around it stays.
    """
    from codelith.knowledge.guide import merge

    folder = Path(args.target).expanduser().resolve()
    root = git_root(folder) or folder
    api = ApiClient()
    if args.project:
        project = _find_project(api, args.project)
    else:
        found = codebase_for_checkout(api.projects(), root)
        if found is None:
            raise CliError("No codebase reads this repository yet. Read it first: codelith analyse .")
        project = found[0]

    guide = api.agent_guide(project["id"], args.format)
    if not args.write:
        o.result(guide)
        if not o.as_json:
            out.file.write(guide["markdown"])
            out.file.flush()
        return 0

    target = root / guide["filename"]
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    target.write_text(merge(existing, guide["markdown"], project["name"]), encoding="utf-8", newline="\n")
    verb = "Updated" if existing else "Wrote"
    o.say(
        f"[green]{verb}[/green] {target} [dim]from the reading at {(guide.get('commit') or '')[:8]}"
        + ("; the rest of the file is unchanged" if existing else "")
        + "[/dim]"
    )
    o.result({"file": str(target), "commit": guide.get("commit"), "updated": bool(existing)})
    return 0


HOOK_MARK = "# codelith: read this repository again after each commit"


def hook_script(root: Path) -> str:
    """
    The post-commit hook. It starts a reading and returns at once, in the background,
    so a commit never waits on it; with no server running it fails quietly, because a
    commit is not the place to complain about that.

    It calls this very interpreter, so it works without the `codelith` script on the
    PATH git hooks run with, and forward slashes so Git for Windows' shell reads it.
    """
    python = Path(sys.executable).as_posix()
    target = root.as_posix()
    return (
        "#!/bin/sh\n"
        f"{HOOK_MARK}\n"
        "# Remove with: codelith hook uninstall\n"
        f'"{python}" -m codelith.cli analyse "{target}" --no-wait >/dev/null 2>&1 &\n'
    )


def hooks_dir(root: Path) -> Path:
    """Where this repository's hooks live: honours `core.hooksPath` and worktrees."""
    import subprocess

    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"], capture_output=True, text=True, check=True
    )
    path = Path(out.stdout.strip())
    return path if path.is_absolute() else (root / path).resolve()


def cmd_hook(args, o: Output) -> int:
    root = git_root(Path(args.target).expanduser().resolve())
    if root is None:
        raise CliError(f"{args.target} is not inside a git repository.")
    hook = hooks_dir(root) / "post-commit"
    ours = hook.exists() and HOOK_MARK in hook.read_text(encoding="utf-8", errors="replace")

    if args.action == "install":
        if hook.exists() and not ours:
            raise CliError(
                f"{hook} already exists and Codelith did not write it, so it is left alone.\n"
                "To read every commit as well, add this line to it:\n  "
                + hook_script(root).splitlines()[-1]
            )
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(hook_script(root), encoding="utf-8", newline="\n")
        try:
            hook.chmod(0o755)
        except OSError:  # pragma: no cover - platform dependent
            pass
        o.say(f"[green]Installed[/green] {hook}. Each commit now starts a reading of the changes.")
        o.result({"hook": str(hook), "installed": True})
        return 0

    if not hook.exists():
        o.say("No post-commit hook to remove.")
        o.result({"hook": str(hook), "installed": False})
        return 0
    if not ours:
        raise CliError(f"{hook} was not written by Codelith, so it is left alone.")
    hook.unlink()
    o.say(f"[green]Removed[/green] {hook}.")
    o.result({"hook": str(hook), "installed": False})
    return 0


def _pretty(agent_name: str) -> str:
    return re.sub(r"_agent$", "", agent_name).replace("_", " ").capitalize()


def cmd_ask(args, o: Output) -> int:
    api = ApiClient()
    project = _find_project(api, args.project)

    answer: list[str] = []
    citations: list[str] = []
    stripped: list[str] = []

    for event in api.ask(project["id"], args.question):
        kind = event.get("type")
        if kind == "token":
            answer.append(event["text"])
            if not o.as_json:
                out.file.write(event["text"])
                out.file.flush()
        elif kind == "done":
            # `done` carries the checked answer, which is not always what streamed:
            # a citation that does not resolve is stripped before it is stored.
            answer = [event.get("text", "".join(answer))]
            citations = event.get("citations") or []
            stripped = event.get("stripped") or []
        elif kind == "error":
            o.fail(f"\n{event.get('message', 'The answer failed.')}")
            return 1

    if not o.as_json:
        out.file.write("\n")
        if citations:
            out.print("\n[dim]Sources[/dim]")
            for c in citations:
                out.print(f"  [dim]·[/dim] {c}")
        if stripped:
            # Worth saying out loud: it is the product's central claim that an
            # unverifiable citation is removed rather than shown.
            out.print(
                f"\n[yellow]{len(stripped)} citation(s) did not resolve "
                "and were removed.[/yellow]"
            )
    o.result(
        {
            "project": project["name"],
            "question": args.question,
            "answer": "".join(answer),
            "citations": citations,
            "stripped": stripped,
        }
    )
    return 0


def cmd_studio(args, o: Output) -> int:
    creds = Credentials.load()
    url = args.url or "http://localhost:5173"

    reachable = True
    try:
        ApiClient(creds).health()
    except Exception:
        reachable = False

    if not reachable:
        o.warn(
            f"The API at {creds.api_url} is not answering — the studio will load but "
            "will not be able to sign you in."
        )
    o.say(f"Opening {url}")
    if not args.no_open:
        webbrowser.open(url)
    o.result({"studio": url, "api": creds.api_url, "api_reachable": reachable})
    return 0 if reachable else 1


def cmd_doctor(args, o: Output) -> int:
    """
    Check the things that fail late and confusingly.

    Ordered by how early they break: no server at all, then no credentials, then a
    model endpoint that is not there, then the dimension mismatch — which does not
    fail at startup at all. It surfaces deep inside ingestion when the first
    embedding is written, and the fix truncates `code_chunks` and re-ingests
    everything, so it is worth an explicit check before any of that happens.
    """
    from codelith.config import get_settings

    creds = Credentials.load()
    api = ApiClient(creds)
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        mark = "[green]ok[/green]" if ok else "[red]no[/red]"
        o.say(f"  {mark}  [bold]{name}[/bold]  [dim]{detail}[/dim]")

    o.say(f"[dim]Checking[/dim] {creds.api_url}")

    try:
        health = api.health()
        record("server", True, f"{creds.api_url} — {health.get('env', 'unknown')}")
        server_up = True
    except Exception as exc:
        record("server", False, f"{creds.api_url} unreachable ({type(exc).__name__})")
        server_up = False

    if server_up:
        try:
            me = api.me()
            record("credentials", True, f"signed in as {me.get('email', '?')}")
        except CliError as exc:
            record("credentials", False, str(exc).splitlines()[0])

    settings = get_settings()
    tiers = {
        "quality": (settings.MODEL_QUALITY, settings.MODEL_QUALITY_BASE_URL),
        "fast": (settings.MODEL_FAST, settings.MODEL_FAST_BASE_URL),
        "embedding": (settings.MODEL_EMBEDDING, settings.MODEL_EMBEDDING_BASE_URL),
    }
    served = _served_models(settings.MODEL_EMBEDDING_BASE_URL)
    for tier, (model, base) in tiers.items():
        if served is None:
            record(f"model:{tier}", False, f"{base} did not answer")
        elif model in served:
            record(f"model:{tier}", True, f"{model} served by {base}")
        else:
            record(f"model:{tier}", False, f"{model} is not loaded at {base}")

    # Reported, not compared. There is nothing to compare against: the width is
    # measured from the model and recorded on the knowledge base it builds, so any
    # model works and a changed one is caught at read time by `embedding_guard`.
    dim = _embedding_dimension(settings)
    if dim is None:
        record(
            "embedding model",
            False,
            f"{settings.MODEL_EMBEDDING} did not answer at "
            f"{settings.MODEL_EMBEDDING_BASE_URL or 'the configured endpoint'}",
        )
    else:
        record(
            "embedding model",
            True,
            f"{settings.MODEL_EMBEDDING} emits {dim}-dimension vectors",
        )

    o.result(checks)
    failed = [c for c in checks if not c["ok"]]
    if failed and not o.as_json:
        o.fail(f"\n{len(failed)} check(s) failed.")
    return 1 if failed else 0


def _served_models(base_url: str) -> set[str] | None:
    import httpx

    try:
        r = httpx.get(f"{base_url.rstrip('/')}/models", timeout=5.0)
        r.raise_for_status()
        return {m["id"] for m in r.json().get("data", [])}
    except Exception:
        return None


def _embedding_dimension(settings) -> int | None:
    """Ask the endpoint what it actually emits, rather than trusting the config."""
    import httpx

    try:
        r = httpx.post(
            f"{settings.MODEL_EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
            json={"model": settings.MODEL_EMBEDDING, "input": "codelith"},
            timeout=30.0,
        )
        r.raise_for_status()
        return len(r.json()["data"][0]["embedding"])
    except Exception:
        return None


def cmd_mcp(args, o: Output) -> int:
    """
    Serve the knowledge base over MCP, on stdin and stdout.

    This is the command an editor launches, so it must be the *only* thing on stdout —
    the protocol is JSON-RPC over that pipe, and one stray line of prose is a parse
    error on the client. `codelith.mcp` speaks it; nothing here prints.

    It exists so `.mcp.json` can say `{"command": "codelith", "args": ["mcp"]}` rather
    than a Python module path plus a `PYTHONPATH` — which is what stood between "read
    the README" and "it works".
    """
    import asyncio

    from codelith.mcp.server import main as serve

    # No banner, no confirmation. Diagnostics belong on stderr and the server logs
    # there already.
    asyncio.run(serve())
    return 0
