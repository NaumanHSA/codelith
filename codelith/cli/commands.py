"""
What each command does.

Kept in one module because they are small and they share a shape: resolve what the
user meant, make one or two API calls, print for a person or for a pipe. The moment
one of these needs its own file it has probably grown a second responsibility.
"""

from __future__ import annotations

import getpass
import re
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


def cmd_analyse(args, o: Output) -> int:
    api = ApiClient()
    source_type, url_or_path, default_name = resolve_source(args.target)
    name = args.name or default_name

    o.step(f"[dim]Reading[/dim] {url_or_path} [dim]as[/dim] {name}")
    project = api.create_with_source(name, source_type, url_or_path, args.branch)
    o.step(f"[dim]Codebase[/dim] #{project['id']} [dim]created[/dim]")

    job = api.analyse(project["id"])
    o.step(f"[dim]Analysis job[/dim] #{job['id']} [dim]started[/dim]")

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
        f"[green]Read[/green] {name} — "
        f"{kb.get('module_count', 0)} modules, {kb.get('entity_count', 0)} facts, "
        f"commit {(kb.get('knowledge_base') or {}).get('commit_sha', '')[:7]}"
    )
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

    dim = _embedding_dimension(settings)
    if dim is None:
        record(
            "vector dimensions",
            False,
            f"could not measure — configured as {settings.VECTOR_DIMENSIONS}",
        )
    elif dim == settings.VECTOR_DIMENSIONS:
        record("vector dimensions", True, f"{dim}, matching VECTOR_DIMENSIONS")
    else:
        record(
            "vector dimensions",
            False,
            f"{settings.MODEL_EMBEDDING} emits {dim}, VECTOR_DIMENSIONS={settings.VECTOR_DIMENSIONS}. "
            "Ingestion will fail when the first embedding is written.",
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
