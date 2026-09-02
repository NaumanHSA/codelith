"""
The knowledge base as something another agent can query.

The tools themselves are `codelith/knowledge/tools.py` and tested there. What is new
here is the seam: an MCP client has no ambient project, so every tool grows a
`codebase_id`, and a client that gets an id wrong must be told what to do rather than
handed an exception.

**Nothing here may raise.** An exception surfaces to the calling agent as a broken
server rather than as a fact about the codebase, and its next move is to stop using the
tool. A sentence explaining the problem lets it try something else — the same rule
`CodebaseTools.run` already follows.
"""

from __future__ import annotations

from types import SimpleNamespace

from codelith.knowledge.constants import KBStatus
from codelith.knowledge.tools import TOOL_SCHEMAS
from codelith.mcp.server import (
    _LIST_CODEBASES,
    SERVER_NAME,
    _dispatch,
    _with_codebase,
    build_server,
)


def _ready_kb_session():
    """A session that finds one analysed codebase, and is never queried further.

    `_dispatch` looks the codebase up before it routes, so a test about routing needs
    that lookup to succeed without needing Postgres to exist.
    """

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            return None

        async def get(self, _model, pk):
            return SimpleNamespace(id=pk, project_id=1, status=KBStatus.READY.value)

    return _Session()


class TestTheToolSurface:
    def test_every_kb_tool_is_exposed(self) -> None:
        exposed = {_with_codebase(s).name for s in TOOL_SCHEMAS}

        assert exposed == {f["function"]["name"] for f in TOOL_SCHEMAS}

    def test_every_tool_requires_a_codebase(self) -> None:
        """In chat the project is ambient; over MCP it cannot be. A server that
        remembers which codebase you meant answers about the wrong one after a client
        reconnects."""
        for schema in TOOL_SCHEMAS:
            tool = _with_codebase(schema)

            assert "codebase_id" in tool.inputSchema["required"], tool.name
            assert tool.inputSchema["properties"]["codebase_id"]["type"] == "integer"

    def test_the_original_schemas_are_not_mutated(self) -> None:
        """`TOOL_SCHEMAS` is shared with the Ask app. Adding a required argument in
        place would make chat send a `codebase_id` the answer path knows nothing
        about."""
        before = [dict(s["function"]["parameters"]) for s in TOOL_SCHEMAS]

        for schema in TOOL_SCHEMAS:
            _with_codebase(schema)

        after = [dict(s["function"]["parameters"]) for s in TOOL_SCHEMAS]
        assert before == after
        assert all("codebase_id" not in s["function"]["parameters"].get("properties", {})
                   for s in TOOL_SCHEMAS)

    def test_listing_codebases_needs_nothing(self) -> None:
        """It is the entry point: ids are not guessable, so the tool that reveals them
        cannot itself require one."""
        assert _LIST_CODEBASES.inputSchema.get("required", []) == []

    def test_the_server_names_itself(self) -> None:
        assert build_server().name == SERVER_NAME


class TestNothingRaises:
    async def test_a_missing_codebase_id_is_explained(self) -> None:
        text = await _dispatch("list_facts", {"kind": "route"})

        assert "codebase_id" in text
        assert "list_codebases" in text

    async def test_an_unknown_tool_is_reported(self, monkeypatch) -> None:
        """`CodebaseTools.run` answers this, and the wiring must reach it rather than
        failing first.

        The session is faked because the assertion is about the seam, not the
        database: a real one turns "does dispatch route an unknown name" into "is
        Postgres up", and the test then fails on a machine where nothing is wrong.
        """
        monkeypatch.setattr("codelith.mcp.server.AsyncSessionLocal", _ready_kb_session)

        text = await _dispatch("no_such_tool", {"codebase_id": 1})

        assert "no_such_tool" in text
