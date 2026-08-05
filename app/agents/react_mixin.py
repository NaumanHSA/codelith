from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool as lc_tool
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import (
    create_react_agent,  # type: ignore[attr-defined]  # Pylance confuses this with langchain.agents.create_react_agent
)

from app.config import get_settings
from app.llm.context_manager import count_tokens_lc, split_for_compaction
from app.llm.langchain_client import get_langchain_llm

logger = structlog.get_logger(__name__)


class ReActMixin:
    """
    Mixin for BaseAgent subclasses that need an inner ReAct tool-use loop.

    The outer LangGraph orchestration graph stays unchanged — this only affects
    what happens inside a single agent's run() call.
    """

    @asynccontextmanager
    async def _mcp_session(self, allowed_path: str) -> AsyncIterator[list]:
        """
        Start an MCP filesystem server scoped to `allowed_path` and yield
        LangChain-compatible tools. Gracefully falls back to [] on failure.
        """
        try:
            from langchain_mcp_adapters.tools import load_mcp_tools
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", allowed_path],
                env=None,
            )
            async with stdio_client(server_params, errlog=open(os.devnull, "w")) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await load_mcp_tools(session)
                    logger.debug("mcp_tools_loaded", count=len(tools), path=allowed_path)
                    yield tools
        except Exception as exc:
            logger.warning("mcp_session_failed", error=str(exc), path=allowed_path)
            yield []

    @asynccontextmanager
    async def _mcp_git_session(self, repo_path: str) -> AsyncIterator[list]:
        """Start an MCP git server for the cloned repo. Falls back to []."""
        try:
            from langchain_mcp_adapters.tools import load_mcp_tools
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-git", "--repository", repo_path],
                env=None,
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await load_mcp_tools(session)
                    logger.debug("mcp_git_tools_loaded", count=len(tools), repo=repo_path)
                    yield tools
        except Exception as exc:
            logger.warning("mcp_git_session_failed", error=str(exc), repo=repo_path)
            yield []

    async def _run_react(
        self,
        *,
        system_prompt: str,
        user_message: str,
        extra_tools: list,
        sandbox_path: str,
        max_iterations: int | None = None,
    ) -> str:
        """
        Run a LangGraph ReAct loop and return the final text response.

        Falls back to the last non-empty assistant message if recursion limit
        is hit. Never raises — callers should handle empty string as signal
        to fall back to single-shot LLM.
        """
        settings = get_settings()
        iterations = max_iterations or settings.REACT_MAX_ITERATIONS
        tracer = self._tracer()  # type: ignore[attr-defined]

        async with self._mcp_session(sandbox_path) as fs_tools:
            # Extra helper: lets the LLM verify exact directory names before guessing paths
            @lc_tool
            def list_project_root() -> str:
                """List the repository root directory to verify exact file and folder names."""
                try:
                    items = sorted(os.listdir(sandbox_path))
                    lines = [f"Repository root: {sandbox_path}", "Contents:"]
                    lines.extend(f"  {item}" for item in items[:60])
                    return "\n".join(lines)
                except Exception as exc:
                    return f"Cannot list repository root: {exc}"

            capped_fs_tools = [
                self._cap_tool_output(t, settings.REACT_TOOL_RESULT_MAX_CHARS) for t in fs_tools
            ]
            all_tools = capped_fs_tools + extra_tools + [list_project_root]
            llm = get_langchain_llm()

            # Intelligent context compaction: when the conversation nears the model
            # window, summarise the older turns via the LLM and feed the summary back so
            # the agent retains awareness of what it already did. Returns llm_input_messages
            # so graph state (and therefore the saved trace) keeps the full raw history.
            compaction_cache = {"summary": "", "covered": 0}

            async def _compact_hook(state: Any) -> dict:
                msgs = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
                if count_tokens_lc(msgs) <= settings.REACT_COMPACT_THRESHOLD_TOKENS:
                    return {"llm_input_messages": msgs}  # under budget → full view

                older, recent = split_for_compaction(msgs, settings.REACT_COMPACT_KEEP_LAST)
                if not older:
                    return {"llm_input_messages": msgs}

                cut = len(older)
                # Only summarise the newly-droppable slice; fold into the running summary.
                if cut > compaction_cache["covered"]:
                    new_slice = older[compaction_cache["covered"]:cut]
                    compaction_cache["summary"] = await self._summarise_react_slice(
                        compaction_cache["summary"], new_slice
                    )
                    compaction_cache["covered"] = cut
                    try:
                        await self._emit_log(  # type: ignore[attr-defined]
                            "info", "Compacted ReAct context",
                            summarised_msgs=cut, kept=len(recent),
                        )
                    except Exception:
                        pass

                summary_msg = HumanMessage(
                    content="[Summary of earlier work this session]\n" + compaction_cache["summary"]
                )
                compacted = [summary_msg, *recent]
                # Last-resort guard: drop oldest recent groups if still over the window,
                # always skipping orphaned ToolMessages to keep tool_calls/results paired.
                while count_tokens_lc(compacted) > settings.LLM_CONTEXT_WINDOW and len(recent) > 1:
                    recent = recent[1:]
                    while recent and type(recent[0]).__name__ == "ToolMessage":
                        recent = recent[1:]
                    compacted = [summary_msg, *recent]
                return {"llm_input_messages": compacted}

            agent = create_react_agent(
                llm,
                all_tools,
                prompt=SystemMessage(content=system_prompt),
                pre_model_hook=_compact_hook,
            )

            # LangGraph counts every message (AIMessage + ToolMessage) as one recursion
            # step, so a tool-call round costs 2. Double the budget to get ~`iterations`
            # actual tool-call rounds.
            config: dict[str, Any] = {"recursion_limit": iterations * 2}

            with tracer(  # type: ignore[attr-defined]
                kind="react_loop",
                agent_id=getattr(self, "name", "unknown"),
                start_message=f"ReAct loop — {len(all_tools)} tools available",
                inputs={
                    "system_prompt": system_prompt,
                    "user_message": user_message,
                    "tools": len(all_tools),
                },
            ) as t:
                # Stream full state after every super-step so that when the recursion
                # limit (or anything else) raises mid-loop, last_state still holds the
                # complete partial history for the trace.
                last_state: dict | None = None
                try:
                    async for chunk in agent.astream(
                        {"messages": [HumanMessage(content=user_message)]},
                        config=config,
                        stream_mode="values",
                    ):
                        last_state = chunk
                    messages = (last_state or {}).get("messages", [])
                    answer = messages[-1].content if messages else ""
                    tool_calls = self._extract_tool_calls(messages)
                    turns = sum(
                        1 for m in messages
                        if type(m).__name__ == "AIMessage" and getattr(m, "tool_calls", None)
                    )
                    # langgraph v1 ends gracefully with this sentinel instead of raising
                    # when the step budget runs out — treat it as a limit hit so callers
                    # fall back instead of using the sentinel as real content.
                    if isinstance(answer, str) and answer.strip().startswith("Sorry, need more steps"):
                        t.set_error(f"ReAct ran out of steps ({iterations} rounds budget)")
                        t.outputs(answer="", iterations="limit_hit", turns=turns, tool_calls=tool_calls)
                        return ""
                    t.outputs(
                        answer=answer,
                        iterations="completed",
                        turns=turns,
                        tool_calls=tool_calls,
                    )
                    return answer

                except GraphRecursionError:
                    t.set_error(f"ReAct hit recursion limit ({iterations} rounds / {iterations * 2} steps)")
                    msgs = (last_state or {}).get("messages", [])
                    tool_calls = self._extract_tool_calls(msgs)
                    for m in reversed(msgs):
                        if type(m).__name__ != "AIMessage":
                            continue
                        content = getattr(m, "content", "") or ""
                        if content and len(str(content)) > 50:
                            t.outputs(answer=str(content), iterations="limit_hit", tool_calls=tool_calls)
                            return str(content)
                    t.outputs(answer="", iterations="limit_hit", tool_calls=tool_calls)
                    return ""

                except Exception as exc:
                    t.set_error(str(exc))
                    msgs = (last_state or {}).get("messages", [])
                    if msgs:
                        t.outputs(answer="", iterations="error", tool_calls=self._extract_tool_calls(msgs))
                    logger.error("react_loop_error", agent=getattr(self, "name", "?"), error=str(exc))
                    return ""

    def _extract_tool_calls(self, messages: list) -> list[dict]:
        """Walk LangGraph message history and return a flat list of tool invocations with results."""
        calls: list[dict] = []
        id_to_call: dict[str, dict] = {}
        for msg in messages:
            cls = type(msg).__name__
            if cls == "AIMessage" and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    entry: dict[str, Any] = {
                        "tool": tc.get("name", ""),
                        "args": tc.get("args", {}),
                    }
                    tc_id = tc.get("id", "")
                    if tc_id:
                        id_to_call[tc_id] = entry
                    calls.append(entry)
            elif cls == "ToolMessage":
                tc_id = getattr(msg, "tool_call_id", "")
                result_text = str(msg.content)[:600]
                # result_text = str(msg.content)
                if tc_id and tc_id in id_to_call:
                    id_to_call[tc_id]["result"] = result_text
                elif calls and "result" not in calls[-1]:
                    calls[-1]["result"] = result_text
        return calls

    def _cap_tool_output(self, tool, max_chars: int):
        """Wrap a tool's async coroutine so oversized string results are truncated.

        Keeps any single file read from blowing the context window. The tool's
        args_schema (what the LLM sees) is untouched — only the runtime result is capped.
        """
        original = getattr(tool, "coroutine", None)
        if original is None:
            return tool  # sync-only or no coroutine — leave as-is

        async def _capped(*args, **kwargs):
            result = await original(*args, **kwargs)
            if isinstance(result, str) and len(result) > max_chars:
                return (
                    result[:max_chars]
                    + f"\n...[truncated — {len(result)} chars total; read a specific line range to see more]"
                )
            return result

        try:
            tool.coroutine = _capped
        except Exception:
            return tool
        return tool

    async def _summarise_react_slice(self, prior_summary: str, messages: list) -> str:
        """LLM-summarise a slice of ReAct history into a dense, cumulative recap.

        Folds `prior_summary` with the new slice so the running summary stays complete.
        Runs only when a loop crosses the compaction threshold.
        """
        tool_calls = self._extract_tool_calls(messages)
        lines: list[str] = []
        for tc in tool_calls:
            name = tc.get("tool", "?")
            args = tc.get("args", {})
            if isinstance(args, dict):
                arg_str = ", ".join(f"{k}={str(v)[:80]}" for k, v in args.items())
            else:
                arg_str = str(args)[:120]
            result = str(tc.get("result", ""))[:300]
            lines.append(f"- {name}({arg_str}) -> {result}")
        for m in messages:
            if type(m).__name__ == "AIMessage":
                content = getattr(m, "content", "") or ""
                if isinstance(content, str) and len(content.strip()) > 30:
                    lines.append(f"- (agent reasoning) {content.strip()[:300]}")
        transcript = "\n".join(lines) if lines else "(no notable tool activity)"

        prior_block = f"Summary so far:\n{prior_summary}\n\n" if prior_summary else ""
        summary_messages = [
            {
                "role": "system",
                "content": (
                    "You compress an AI agent's work log into a dense, factual running summary. "
                    "Capture concretely: files read and their key contents, exact paths confirmed, "
                    "sections or claims already written or verified, decisions made, and what still "
                    "remains to do. Preserve specific names and paths. No preamble, no fluff."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{prior_block}New activity to fold into the summary:\n{transcript}\n\n"
                    "Return the updated running summary only."
                ),
            },
        ]
        try:
            return await self._call_llm(summary_messages, task_type="summarize")  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("react_summary_failed", error=str(exc))
            return (prior_summary + "\n" + transcript).strip()[:4000]

    def _make_graph_tool(self, project_id: int):
        """Return a Neo4j code-graph query tool as a LangChain tool."""
        from app.memory.graph_store import GraphStore

        @lc_tool
        async def query_code_graph(query: str) -> str:
            """Query the code dependency graph.

            Supported query types (use plain English):
            - "imports of app/main.py" → what does this file import?
            - "dependents of app/services/auth.py" → what files import this?
            - "symbols in app/models/" → classes and functions in this directory
            - "module overview" → top-level module dependency summary
            """
            q = query.lower().strip()
            try:
                async with GraphStore() as graph:
                    if q.startswith("imports of "):
                        path = query.split("imports of ", 1)[1].strip()
                        deps = await graph.get_imports(project_id, path)
                        return f"Imports of {path}:\n" + ("\n".join(deps) if deps else "(none found)")

                    if q.startswith("dependents of "):
                        path = query.split("dependents of ", 1)[1].strip()
                        deps = await graph.get_dependents(project_id, path)
                        return f"Files that import {path}:\n" + ("\n".join(deps) if deps else "(none found)")

                    if q.startswith("symbols in "):
                        prefix = query.split("symbols in ", 1)[1].strip()
                        rows = await graph.get_symbols(project_id, path_prefix=prefix)
                        if not rows:
                            return f"No symbols found under {prefix}"
                        lines = [f"{r['file']}:{r['line']} {r['kind']} {r['name']}" for r in rows[:40]]
                        return "\n".join(lines)

                    # Default: module overview
                    rows = await graph.get_module_overview(project_id)
                    if not rows:
                        return "No module graph data available."
                    lines = [f"{r['file']} imports {r['import_count']} modules: {', '.join(r['imports'][:3])}" for r in rows[:20]]
                    return "Module dependency overview:\n" + "\n".join(lines)

            except Exception as exc:
                return f"Graph query failed: {exc}"

        return query_code_graph

    def _make_search_tool(self, project_id: int, db):
        """Return a pgvector semantic search tool as a LangChain tool."""
        from app.tools.search_tools import semantic_search

        @lc_tool
        async def search_codebase(query: str) -> str:
            """Search the indexed codebase for relevant code chunks matching the query."""
            results = await semantic_search(query=query, project_id=project_id, db=db, limit=6)
            if not results:
                return "No results found."
            lines = []
            for r in results:
                lines.append(f"### {r['path']} (lines {r.get('start_line','?')}-{r.get('end_line','?')})\n```{r.get('language','')}\n{r['content'][:800]}\n```")
            return "\n\n".join(lines)

        return search_codebase

    def _save_memory_checkpoint(self, sandbox, name: str, data: Any) -> None:
        """Persist agent progress to sandbox/memory/{name}.json."""
        try:
            path = sandbox.memory_path(name)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("memory_checkpoint_failed", name=name, error=str(exc))

    def _load_memory_checkpoint(self, sandbox, name: str) -> Any | None:
        """Load a previously saved memory checkpoint."""
        try:
            path = sandbox.memory_path(name)
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("memory_load_failed", name=name, error=str(exc))
        return None
