"""
Codelith's knowledge base, over MCP.

Every coding agent currently reads a repository by grepping and guessing, from scratch,
every session. Codelith has already read it — chunked, embedded, and with an import
graph — and pinned the result to a commit. This exposes that so Claude Code, Cursor and
anything else speaking MCP can ask instead of re-deriving.

**It is not an app.** Apps consume the knowledge base and add something of their own;
this adds nothing. It is a second transport over the base: six of the tools come from
`codelith/knowledge/tools.py`, already in tool-schema shape because `Ask` needed them,
and `before_edit` from `codelith/knowledge/preflight.py`. The isolation rules therefore
do not apply the way they do to `codelith/apps/` — there is nothing here to keep
separate from the base, only a different way in.

`before_edit` is the one that changes what Codelith is for. The other six answer
questions about a codebase; that one is called *before* a change, and turns the
knowledge base into something an agent consults rather than something a person reads.

**Read-only, and local.** Nothing here writes, and nothing reaches the network beyond
the databases Codelith already talks to. The same claim the product makes holds for the
agents that connect to it.

Run it with `python -m codelith.mcp`, or point an MCP client at that command.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from codelith.db.session import AsyncSessionLocal
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.preflight import PreflightService
from codelith.knowledge.tools import TOOL_SCHEMAS, CodebaseTools
from codelith.models.agent_call import AgentCall
from codelith.models.knowledge import KnowledgeBase
from codelith.models.project import Project

logger = structlog.get_logger(__name__)

SERVER_NAME = "codelith"

#: Extra tool, not in `TOOL_SCHEMAS`. A chat session already knows which project it is
#: about; an MCP client does not, and asking it to guess a numeric id is worse than
#: telling it what exists.
_LIST_CODEBASES = Tool(
    name="list_codebases",
    description=(
        "List the codebases Codelith has analysed, with their id and commit. Call this "
        "first — every other tool needs a codebase id, and the ids are not guessable."
    ),
    inputSchema={"type": "object", "properties": {}},
)


#: The one worth calling before an edit rather than after.
#:
#: Not in `TOOL_SCHEMAS` on purpose. Those six are what an *answering* model reaches
#: for mid-question, and `Ask` offers exactly those; this is for an agent about to
#: change something, which is a different moment and a different caller. Putting it in
#: the shared list would hand it to a model that has no edit to make.
_PREFLIGHT = {
    "type": "function",
    "function": {
        "name": "before_edit",
        "description": (
            "Call this BEFORE editing a file or a function. Given a path or a symbol "
            "name, returns what depends on it — direct importers, everything that "
            "reaches it transitively, its call sites, whether any test covers it, and "
            "which written pages describe it. Cheap: indexed lookups, no model call. "
            "The failure it prevents is an edit that is correct in the file and breaks "
            "four callers you never looked for."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "A repository path (codelith/llm/client.py, or just client.py) "
                        "or a function/class name (select_spec, Service.fetch)."
                    ),
                }
            },
            "required": ["target"],
        },
    },
}


#: The other half of `before_edit`: after the edit, before the agent says it is done.
#: Not in the shared list for the same reason — a chat model has no change to review.
_REVIEW = {
    "type": "function",
    "function": {
        "name": "review_changes",
        "description": (
            "Call this AFTER editing, before you say the work is done. Reads the uncommitted "
            "change in the repository and checks it against what Codelith knows about the "
            "codebase: which parts and functions it touches, what else could break, which "
            "tests to run, which written pages now need checking, routes or settings it "
            "adds or removes, and whether it breaks the codebase's shape — an import that "
            "runs backwards between parts, a new dependency between two parts, a new loop, "
            "a deleted file something still imports. No model call. Fix anything under "
            "'Stop and look' before finishing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "The repository folder. Optional: defaults to the folder the codebase "
                        "is read from, or the directory this server runs in."
                    ),
                },
                "against": {
                    "type": "string",
                    "description": (
                        "A commit or branch to compare with. Optional: defaults to the commit "
                        "the knowledge was read at, or HEAD."
                    ),
                },
            },
            "required": [],
        },
    },
}


def _with_codebase(schema: dict) -> Tool:
    """One of the KB tools, plus the codebase it applies to.

    In chat the project is ambient. Over MCP it has to be an argument, so every tool
    gains the same required field rather than the server keeping hidden state — a
    server that remembers which codebase you meant is a server that answers about the
    wrong one after a client reconnects.
    """
    fn = schema["function"]
    params = json.loads(json.dumps(fn["parameters"]))  # copy; the original is shared
    params.setdefault("properties", {})["codebase_id"] = {
        "type": "integer",
        "description": "From list_codebases.",
    }
    params["required"] = [*params.get("required", []), "codebase_id"]
    return Tool(name=fn["name"], description=fn["description"], inputSchema=params)


def build_server() -> Server:
    server: Server = Server(SERVER_NAME)
    tools = [
        _LIST_CODEBASES,
        _with_codebase(_PREFLIGHT),
        _with_codebase(_REVIEW),
        *(_with_codebase(s) for s in TOOL_SCHEMAS),
    ]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """
        Never raises.

        An exception here surfaces to the calling agent as a broken server rather than
        as a fact about the codebase, and the agent's next move is to stop using the
        tool. A sentence explaining the problem lets it try something else — the same
        rule `CodebaseTools.run` already follows.
        """
        args = dict(arguments or {})
        ok = True
        try:
            # A copy: dispatch takes the codebase id out of what it is handed.
            text = await _dispatch(name, dict(args), client=_client_name(server))
        except Exception as exc:  # pragma: no cover - defensive boundary
            logger.warning("mcp_tool_failed", tool=name, error=str(exc))
            text = f"That lookup failed: {exc}"
            ok = False
        await record_call(_client_name(server), name, args, text, ok)
        return [TextContent(type="text", text=text)]

    return server


def _client_name(server: Server) -> str:
    """What the agent called itself in the handshake, or `unknown`."""
    try:
        params = server.request_context.session.client_params
        info = getattr(params, "clientInfo", None) if params else None
        return (getattr(info, "name", None) or "unknown")[:120]
    except Exception:  # noqa: BLE001 - outside a request, or the SDK moved it
        return "unknown"


async def record_call(client: str, tool: str, args: dict[str, Any], text: str, ok: bool) -> None:
    """
    Keep one row per call, so the studio can show which agents are attached and what
    they asked. Never raises: an answer the agent needs must not fail because its
    record could not be written.
    """
    try:
        raw = args.get("codebase_id")
        kb_id = int(raw) if raw is not None else None
        rest = {k: v for k, v in args.items() if k != "codebase_id"}
        first = next((line for line in text.strip().splitlines() if line.strip()), "")
        async with AsyncSessionLocal() as db:
            project_id = None
            if kb_id is not None:
                kb = await db.get(KnowledgeBase, kb_id)
                project_id = kb.project_id if kb else None
            db.add(
                AgentCall(
                    client=client,
                    tool=tool,
                    kb_id=kb_id,
                    project_id=project_id,
                    args_json=rest,
                    summary=first[:300] or None,
                    ok=ok,
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning("mcp_call_not_recorded", tool=tool, error=str(exc))


async def _dispatch(name: str, args: dict[str, Any], client: str | None = None) -> str:
    if name == "list_codebases":
        return await _list_codebases()

    codebase_id = args.pop("codebase_id", None)
    if codebase_id is None:
        return "This tool needs a codebase_id. Call list_codebases first."

    async with AsyncSessionLocal() as db:
        kb = await db.get(KnowledgeBase, int(codebase_id))
        if kb is None:
            return f"No codebase with id {codebase_id}. Call list_codebases."
        if not KBStatus(kb.status).can_serve_features:
            return (
                f"That codebase is {kb.status} and cannot be queried yet. "
                "Analysis has to finish first."
            )

        if name == "review_changes":
            return await _review(db, kb, args, client)

        if name == "before_edit":
            report = await PreflightService(db, kb.id, kb.project_id).inspect(
                str(args.get("target") or "")
            )
            text = report.brief()
        else:
            text, _evidence = await CodebaseTools(db, kb.id, kb.project_id).run(name, args)
        return text + "\n\n" + await _provenance(db, kb)


async def _review(db, kb, args: dict[str, Any], client: str | None) -> str:
    """Collect the working copy's change, review it, keep it for the studio."""
    import asyncio
    import os
    from pathlib import Path

    from codelith.knowledge import changes as change_io
    from codelith.services import review_service

    folder = Path(args.get("path") or (await review_service.local_folder(db, kb.project_id)) or os.getcwd())
    against = args.get("against") or None

    def collect():
        base = against
        if not base:
            base = kb.commit_sha if kb.commit_sha and change_io.has_commit(folder, kb.commit_sha) else "HEAD"
        return change_io.collect(folder, base)

    try:
        change = await asyncio.to_thread(collect)
    except change_io.ChangeError as exc:
        return f"Could not read the change: {exc}"
    if not change.files:
        return (
            f"Nothing has changed in {folder} against {change.base[:8]}. "
            "Review reads uncommitted and untracked files; pass `against` to compare with another commit."
        )
    row, review = await review_service.run_and_keep(
        db, kb.project_id, change, source="mcp", client=client, kb=kb
    )
    return review.brief() + "\n" + f"(Kept as review #{row.id}; it is on the codebase's Review page in the studio.)"


#: Commits-behind per codebase, briefly. An agent calls several tools in a row, and the
#: answer does not change between them.
_behind_cache: dict[int, tuple[float, int | None]] = {}
_BEHIND_TTL = 30.0


async def _provenance(db, kb) -> str:
    """
    The line every answer ends with: which commit it describes, and — for a codebase on
    this machine — how far the code has moved since. An answer about code as it was is
    accurate and still misleading if nothing says so.
    """
    commit = (getattr(kb, "commit_sha", None) or "")[:8] or "an unknown commit"
    try:
        behind = await _commits_behind(db, kb)
    except Exception as exc:
        # Never lose an answer over the line that dates it — the log line included: a
        # rendered traceback draws boxes a cp1252 console cannot encode, and the write
        # itself raised. The error as text says enough.
        logger.warning("mcp_provenance_failed", kb_id=getattr(kb, "id", None), error=f"{type(exc).__name__}: {exc}")
        behind = None
    if behind:
        return (
            f"(Read at {commit}. The code has {behind} newer commit{'s' if behind != 1 else ''} "
            "since; analyse it again for answers about the current code.)"
        )
    if kb.status == KBStatus.STALE:
        return f"(Read at {commit}. A newer reading of this codebase exists; call list_codebases.)"
    return f"(Read at {commit}, the latest reading of this codebase.)"


async def _commits_behind(db, kb) -> int | None:
    import asyncio
    import time

    from sqlalchemy import select

    from codelith.models.project import ProjectSource
    from codelith.services.auto_read import local_head
    from codelith.services.head_check import commits_between

    if not getattr(kb, "commit_sha", None):
        return None
    hit = _behind_cache.get(kb.id)
    if hit and time.monotonic() - hit[0] < _BEHIND_TTL:
        return hit[1]
    behind: int | None = None
    source = (
        await db.execute(
            select(ProjectSource).where(ProjectSource.project_id == kb.project_id).order_by(ProjectSource.id).limit(1)
        )
    ).scalar_one_or_none()
    # Local only: a hosted repository would cost a network round trip per tool call.
    if source is not None and source.source_type == "local" and kb.commit_sha:
        head = await asyncio.to_thread(local_head, source.url_or_path)
        if head and head != kb.commit_sha:
            behind = await asyncio.to_thread(commits_between, source.url_or_path, kb.commit_sha, head)
    _behind_cache[kb.id] = (time.monotonic(), behind)
    return behind


async def _list_codebases() -> str:
    """
    What is available to ask about.

    Only analysed codebases are listed. Offering one whose analysis is still running
    invites a client to call six tools against an empty index and conclude the
    repository is empty.
    """
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(KnowledgeBase, Project.name)
                .join(Project, Project.id == KnowledgeBase.project_id)
                .order_by(KnowledgeBase.id.desc())
            )
        ).all()

    usable = [(kb, name) for kb, name in rows if KBStatus(kb.status).can_serve_features]
    if not usable:
        return (
            "No analysed codebases yet. Add one in the Codelith studio and run an "
            "analysis; nothing here can be answered until a knowledge base exists."
        )

    lines = [f"{len(usable)} codebase(s) available:", ""]
    for kb, name in usable:
        commit = (kb.commit_sha or "")[:8] or "unknown commit"
        stats = kb.stats_json or {}
        lines.append(
            f"  codebase_id={kb.id}  {name}  @{commit}  "
            f"({stats.get('modules', '?')} modules, {stats.get('indexed_chunks', '?')} chunks)"
            + ("  [stale — the repository has moved on]" if kb.status == KBStatus.STALE else "")
        )
    return "\n".join(lines)


async def main() -> None:
    """
    Serve until the client disconnects, then let the process end.

    The `dispose` is not tidiness. `aiosqlite` runs each connection on its own
    non-daemon thread, so an engine that still holds one keeps the interpreter alive
    after the stdio loop returns — the editor closes the pipe, the server stops
    answering, and the process never exits. `scripts/seed_dev.py` hung for exactly
    this reason before it started disposing its engine.
    """
    server = build_server()
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        from codelith.db.session import engine

        await engine.dispose()


__all__ = ["build_server", "main", "SERVER_NAME"]
