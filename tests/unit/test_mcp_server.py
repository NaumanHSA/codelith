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

import pytest

from codelith.knowledge.constants import KBStatus
from codelith.knowledge.tools import TOOL_SCHEMAS
from codelith.mcp.server import (
    _LIST_CODEBASES,
    _PREFLIGHT,
    SERVER_NAME,
    _dispatch,
    _with_codebase,
    build_server,
    main,
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


class TestThePreflightTool:
    """
    `before_edit` is the reason an agent connects at all: the other six answer
    questions about a codebase, this one is called before changing it.
    """

    def test_it_is_offered_alongside_the_question_tools(self) -> None:
        tool = _with_codebase(_PREFLIGHT)

        assert tool.name == "before_edit"
        assert tool.inputSchema["required"] == ["target", "codebase_id"]

    def test_it_is_not_in_the_shared_schemas(self) -> None:
        """
        `TOOL_SCHEMAS` is what an *answering* model reaches for mid-question, and Ask
        offers exactly those. Putting the pre-flight in that list would hand it to a
        model with no edit to make.
        """
        assert "before_edit" not in {s["function"]["name"] for s in TOOL_SCHEMAS}

    def test_its_description_says_when_to_call_it(self) -> None:
        """A tool a model cannot tell apart from another is a tool it picks at
        random. This one is distinguished by *when*, not by what it returns."""
        assert "BEFORE" in _PREFLIGHT["function"]["description"]

    async def test_it_routes_to_the_preflight_not_the_tool_runner(
        self, monkeypatch
    ) -> None:
        seen: dict = {}

        class _Report:
            def brief(self) -> str:
                return "the pre-flight answer"

        class _Service:
            def __init__(self, _db, kb_id, project_id):
                seen["kb"] = (kb_id, project_id)

            async def inspect(self, target):
                seen["target"] = target
                return _Report()

        monkeypatch.setattr("codelith.mcp.server.AsyncSessionLocal", _ready_kb_session)
        monkeypatch.setattr("codelith.mcp.server.PreflightService", _Service)

        text = await _dispatch("before_edit", {"codebase_id": 7, "target": "app/auth.py"})

        assert text == "the pre-flight answer"
        assert seen == {"kb": (7, 1), "target": "app/auth.py"}


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


class TestItLetsTheProcessEnd:
    """
    An editor starts this server and closes the pipe when it is done with it. The
    process has to actually go away.

    `aiosqlite` runs every connection on its own **non-daemon** thread, so an engine
    that has served one request keeps the interpreter alive after the stdio loop
    returns. Measured: a process that opens a session and does not dispose the engine
    was still running twenty seconds after its work finished. Every editor session
    would leave one behind.
    """

    async def test_the_engine_is_disposed_when_the_loop_returns(self, monkeypatch) -> None:
        disposed: list[bool] = []
        monkeypatch.setattr(*_fake_stdio())
        monkeypatch.setattr(*_fake_run())
        monkeypatch.setattr("codelith.db.session.engine", _FakeEngine(disposed))

        await main()

        assert disposed == [True]

    async def test_it_is_disposed_even_when_the_server_fails(self, monkeypatch) -> None:
        """A crash must not be the one path that leaks the process."""
        disposed: list[bool] = []
        monkeypatch.setattr(*_fake_stdio())
        monkeypatch.setattr(*_fake_run(boom=True))
        monkeypatch.setattr("codelith.db.session.engine", _FakeEngine(disposed))

        with pytest.raises(RuntimeError):
            await main()

        assert disposed == [True]


class _FakeEngine:
    """`AsyncEngine.dispose` cannot be replaced in place — the class uses slots — so
    the whole engine is swapped for the length of the test."""

    def __init__(self, into: list) -> None:
        self._into = into

    async def dispose(self) -> None:
        self._into.append(True)


def _fake_stdio():
    class _Stdio:
        async def __aenter__(self):
            return (None, None)

        async def __aexit__(self, *_exc):
            return None

    return "codelith.mcp.server.stdio_server", lambda: _Stdio()


def _fake_run(*, boom: bool = False):
    async def _run(self, *_args, **_kwargs):
        if boom:
            raise RuntimeError("the client went away mid-request")

    from mcp.server import Server

    return Server, "run", _run
