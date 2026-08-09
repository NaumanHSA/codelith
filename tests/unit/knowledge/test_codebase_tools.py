"""
The tools a question-answering model may reach for.

One retrieval pass answers most questions. Measured on the twenty-question set, six
of twenty said the evidence was insufficient — and two of those six were true
absences, since the repository genuinely has no scheduled tasks and no authentication
layer. So roughly one question in five wanted a second look.

Two properties matter more than any individual tool:

* **An empty result is an answer, not a failure.** "The analysis found no
  scheduled_task" is a finding — it looked and there are none. A tool that returns
  "nothing found" invites the model to keep searching for something that is not there.
* **Nothing raises.** A tool that throws ends the answer. One that returns a sentence
  explaining the problem lets the model try something else, which is what a person
  would do.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.knowledge.tools import TOOL_NAMES, TOOL_SCHEMAS, CodebaseTools


class _Chunk(SimpleNamespace):
    pass


def _chunk(path: str, start: int = 1, end: int = 10, content: str = "code") -> _Chunk:
    return _Chunk(source_path=path, start_line=start, end_line=end, content=content)


@pytest.fixture
def tools(monkeypatch) -> CodebaseTools:
    t = CodebaseTools(db=None, kb_id=1, project_id=1)  # type: ignore[arg-type]

    async def _no_chunks(kb_id, paths):
        return []

    t.store = SimpleNamespace(get_by_paths=_no_chunks)  # type: ignore[assignment]
    t.repos = SimpleNamespace(  # type: ignore[assignment]
        entities=SimpleNamespace(list_by_kind=lambda *a, **k: _async([]))
    )
    return t


async def _async(value):
    return value


class TestSchemas:
    def test_every_schema_is_well_formed(self) -> None:
        for schema in TOOL_SCHEMAS:
            fn = schema["function"]
            assert fn["name"] and fn["description"]
            assert fn["parameters"]["type"] == "object"
            assert fn["parameters"]["required"]

    def test_every_declared_tool_has_a_handler(self) -> None:
        """A schema the model can call and nothing implements is a promise that
        fails at the worst moment."""
        t = CodebaseTools(db=None, kb_id=1, project_id=1)  # type: ignore[arg-type]

        for name in TOOL_NAMES:
            assert hasattr(t, f"_{name}"), f"{name} is offered but not implemented"

    def test_list_facts_only_offers_kinds_the_schema_knows(self) -> None:
        """The enum is what stops the model inventing an entity kind and getting an
        empty result that reads as "this repository has none"."""
        from app.knowledge.constants import EntityKind

        schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "list_facts")
        offered = set(schema["function"]["parameters"]["properties"]["kind"]["enum"])

        assert offered <= {str(k) for k in EntityKind}


class TestNothingRaises:
    """A tool that throws ends the answer. One that explains itself lets the model
    recover, which is what a person would do."""

    async def test_an_unknown_tool_is_reported_not_raised(self, tools) -> None:
        text, evidence = await tools.run("no_such_tool", {})

        assert "No such tool" in text
        assert evidence == []

    async def test_missing_arguments_are_reported(self, tools) -> None:
        for name in ("search_code", "read_file", "find_callers", "find_dependents"):
            text, evidence = await tools.run(name, {})
            assert "needs a" in text
            assert evidence == []

    async def test_a_failing_handler_is_caught(self, tools, monkeypatch) -> None:
        async def _boom(args):
            raise RuntimeError("the graph is on fire")

        monkeypatch.setattr(tools, "_search_code", _boom)

        text, evidence = await tools.run("search_code", {"query": "x"})

        assert "failed" in text
        assert evidence == []


class TestEmptyResultsAreAnswers:
    async def test_no_facts_of_a_kind_is_stated_as_a_finding(self, tools) -> None:
        """The failure this prevents: the model reads "nothing found", assumes it
        searched badly, and burns its budget looking for something the analysis has
        already established is absent."""
        text, evidence = await tools.run("list_facts", {"kind": "scheduled_task"})

        assert "no scheduled_task" in text
        assert "not a gap" in text
        assert evidence == []

    async def test_a_missing_file_says_it_may_be_excluded(self, tools) -> None:
        text, _ = await tools.run("read_file", {"path": "app/ghost.py"})

        assert "not in this knowledge base" in text

    async def test_no_callers_does_not_claim_there_are_none(self, tools, monkeypatch) -> None:
        """Call edges resolve only where the callee is unambiguous, so silence is not
        proof. Saying "nothing calls this" would be a stronger claim than the data
        supports."""
        class _Graph:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get_callers(self, project_id, symbol):
                return []

        monkeypatch.setattr("app.knowledge.tools.GraphStore", _Graph)

        text, _ = await tools.run("find_callers", {"symbol": "ghost"})

        assert "not proof" in text


class TestResultsBecomeEvidence:
    """Everything a tool returns joins the pool the citation check runs against, so a
    citation to something the loop fetched resolves like any other."""

    async def test_a_search_result_carries_its_location(self, tools, monkeypatch) -> None:
        async def _search(query, limit=6, chunk_types=None):
            return [_chunk("app/db/session.py", 12, 40, "def make_engine(): ...")]

        monkeypatch.setattr(
            "app.knowledge.tools.SectionContextBuilder",
            lambda **kwargs: SimpleNamespace(_search_chunks=_search),
        )

        text, evidence = await tools.run("search_code", {"query": "engine"})

        assert evidence[0].title == "app/db/session.py:12-40"
        assert "app/db/session.py:12-40" in text
        assert evidence[0].why

    async def test_a_file_read_returns_its_chunks_in_order(self, tools) -> None:
        async def _by_paths(kb_id, paths):
            return [_chunk("app/x.py", 40, 60), _chunk("app/x.py", 1, 20)]

        tools.store = SimpleNamespace(get_by_paths=_by_paths)  # type: ignore[assignment]

        _, evidence = await tools.run("read_file", {"path": "app/x.py"})

        assert [e.title for e in evidence] == ["app/x.py:1-20", "app/x.py:40-60"]

    async def test_a_traversal_becomes_one_piece_of_evidence(self, tools, monkeypatch) -> None:
        class _Graph:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get_dependents(self, project_id, path):
                return ["app/a.py", "app/b.py"]

        monkeypatch.setattr("app.knowledge.tools.GraphStore", _Graph)

        text, evidence = await tools.run("find_dependents", {"path": "app/x.py"})

        assert len(evidence) == 1
        assert evidence[0].kind == "graph"
        assert "app/a.py" in text
