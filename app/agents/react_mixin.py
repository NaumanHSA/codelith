from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import structlog
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent  # type: ignore[attr-defined]  # Pylance confuses this with langchain.agents.create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool as lc_tool

from app.config import get_settings
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
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from langchain_mcp_adapters.tools import load_mcp_tools

            server_params = StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", allowed_path],
                env=None,
            )
            async with stdio_client(server_params) as (read, write):
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
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from langchain_mcp_adapters.tools import load_mcp_tools

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
        repo_path: str | None = None,
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
            git_tools: list = []
            if repo_path:
                # nested context managers don't compose cleanly here,
                # so we run git session manually with a try/except fallback
                try:
                    from mcp import ClientSession, StdioServerParameters
                    from mcp.client.stdio import stdio_client
                    from langchain_mcp_adapters.tools import load_mcp_tools

                    server_params = StdioServerParameters(
                        command="npx",
                        args=["-y", "@modelcontextprotocol/server-git", "--repository", repo_path],
                        env=None,
                    )
                    async with stdio_client(server_params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            git_tools = await load_mcp_tools(session)
                except Exception as exc:
                    logger.warning("mcp_git_inline_failed", error=str(exc))

            all_tools = fs_tools + git_tools + extra_tools
            llm = get_langchain_llm()

            agent = create_react_agent(
                llm,
                all_tools,
                prompt=SystemMessage(content=system_prompt),
            )

            config: dict[str, Any] = {"recursion_limit": iterations}

            with tracer(  # type: ignore[attr-defined]
                kind="react_loop",
                agent_id=getattr(self, "name", "unknown"),
                start_message=f"ReAct loop — {len(all_tools)} tools available",
                inputs={"user_message": user_message[:300], "tools": len(all_tools)},
            ) as t:
                try:
                    result = await agent.ainvoke(
                        {"messages": [HumanMessage(content=user_message)]},
                        config=config,
                    )
                    answer = result["messages"][-1].content
                    t.outputs(answer_preview=str(answer)[:400], iterations="completed")
                    return answer

                except GraphRecursionError:
                    t.set_error(f"ReAct hit recursion limit ({iterations})")
                    # Return best partial answer from message history
                    msgs = result.get("messages", []) if "result" in dir() else []  # type: ignore
                    for m in reversed(msgs):
                        content = getattr(m, "content", "") or ""
                        if content and len(content) > 50:
                            t.outputs(answer_preview=str(content)[:400], iterations="limit_hit")
                            return str(content)
                    return ""

                except Exception as exc:
                    t.set_error(str(exc))
                    logger.error("react_loop_error", agent=getattr(self, "name", "?"), error=str(exc))
                    return ""

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
