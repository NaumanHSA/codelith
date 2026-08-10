"""
Prose in the index, and the policy that keeps it in its place.

Docstrings and READMEs carry intent no AST holds. They are also the most likely
thing in a repository to be wrong, and a natural-language query is lexically much
closer to a paragraph of prose than to the function implementing it — so similarity
ranking systematically prefers prose to the code it describes.

Two failures this guards against, both of which look like success:

* **Laundering.** Documentation generation that retrieves the repository's README
  can paraphrase it back out as "generated documentation". The output looks right
  and the tool has done nothing.
* **Crowding.** Under a shared ranking, well-written prose displaces the source that
  would actually answer the question. "Prefer the code" in a prompt is a soft
  constraint that fails exactly when the context is tight, which is when it matters.

So the guarantee is measured in tokens, not asserted about instructions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.knowledge import policy
from codelith.knowledge.builder import SourceFile, chunk_files, chunk_prose
from codelith.knowledge.policy import (
    DOCS_GENERATION,
    QUESTION_ANSWERING,
    RetrievalPolicy,
)
from codelith.knowledge.retrieval import SectionContextBuilder

CODE_FILE = '''
"""Session handling for the database.

This module owns the async engine and is the only place a connection is created.
Everything else asks for a session rather than building one, which is what keeps
the pool bounded under load.
"""


def make_engine(url):
    """Build the async engine.

    The pool size is deliberately small: analysis runs are long and mostly idle,
    so a large pool holds connections open for no benefit whatsoever.
    """
    return url
'''

README = """# The Project

A tool for generating documentation.

## Architecture

The engine lives in `app/db/session.py` and is created once at startup.

## Deployment

Run it with docker compose. The database is Postgres.
"""


def _chunk(path, content, chunk_type, line=1):
    return SimpleNamespace(
        source_path=path, content=content, chunk_type=chunk_type,
        language="python" if chunk_type == policy.CODE else "markdown",
        start_line=line, end_line=line + 5,
    )


class _Store:
    """Enough VectorStore for the builder: returns whatever the filter asks for."""

    def __init__(self, code: list, prose: list) -> None:
        self.code, self.prose = code, prose
        self.calls: list[frozenset] = []

    async def get_by_paths(self, kb_id, paths):
        return []

    async def search(self, *, chunk_types=None, limit=10, **kwargs):
        wanted = frozenset(chunk_types or {policy.CODE})
        self.calls.append(wanted)
        out = []
        if policy.CODE in wanted:
            out += self.code
        if wanted & policy.PROSE_TYPES:
            out += [c for c in self.prose if c.chunk_type in wanted]
        return out[:limit]


@pytest.fixture
def builder(monkeypatch):
    """A builder wired to fakes, so the policy is what is under test."""

    def _make(retrieval_policy, *, token_budget=800, code=None, prose=None):
        async def _embedding(_text):
            return [0.0] * 8

        monkeypatch.setattr("codelith.knowledge.retrieval.create_embedding", _embedding)

        b = SectionContextBuilder(
            db=None,  # type: ignore[arg-type]
            kb_id=1,
            project_id=1,
            token_budget=token_budget,
            retrieval_policy=retrieval_policy,
        )
        b.store = _Store(
            code if code is not None else [
                _chunk("app/db/session.py", "def make_engine(url):\n    return url", policy.CODE, i)
                for i in range(1, 12)
            ],
            prose if prose is not None else [
                _chunk("README.md", "The engine lives in app/db/session.py.", policy.MARKDOWN),
                _chunk("app/db/session.py", "make_engine: Build the async engine.", policy.DOCSTRING),
            ],
        )

        async def _no_narratives(_doc_type):
            return []

        b._narratives_for = _no_narratives  # type: ignore[method-assign]
        b.repos = SimpleNamespace(
            modules=SimpleNamespace(
                find_for_files=lambda *a, **k: _async([]),
                list_by_kb=lambda *a, **k: _async([]),
            )
        )
        return b

    return _make


async def _async(value):
    return value


SECTION = {"name": "Sessions", "focus": "how the engine is built", "key_files": []}


class TestDocumentationGenerationNeverSeesProse:
    """The laundering failure. A generator that retrieves the repository's own docs
    can paraphrase them back out and appear to have worked."""

    async def test_no_prose_reaches_the_context(self, builder) -> None:
        b = builder(DOCS_GENERATION)

        context = await b.build(SECTION, "architecture")

        assert context.prose_blocks == []
        assert "unverified" not in context.render().lower()

    async def test_the_store_is_never_even_asked_for_prose(self, builder) -> None:
        """Filtering after retrieval would still let prose influence ranking and
        would be one refactor away from leaking. It is excluded at the query."""
        b = builder(DOCS_GENERATION)

        await b.build(SECTION, "architecture")

        assert b.store.calls, "expected at least one search"
        for wanted in b.store.calls:
            assert wanted & policy.PROSE_TYPES == frozenset()

    async def test_it_is_the_default_for_every_existing_caller(self) -> None:
        """The writer, reviser and planner construct this without naming a policy.
        A default that admitted prose would silently change all of them."""
        b = SectionContextBuilder(db=None, kb_id=1, project_id=1)  # type: ignore[arg-type]

        assert b.policy is DOCS_GENERATION
        assert b.policy.allow_prose is False

    async def test_an_explicit_prose_request_is_still_refused(self, builder) -> None:
        """Defence in depth: even a caller that asks for prose by name gets none
        under a code-only policy."""
        b = builder(DOCS_GENERATION)

        chunks = await b._search_chunks("anything", limit=5, chunk_types=policy.PROSE_TYPES)

        assert chunks == []


class TestCodeCannotBeCrowdedOut:
    """The guarantee is a budget, not a prompt instruction."""

    async def test_code_keeps_its_reserved_share_against_perfect_prose(self, builder) -> None:
        """Prose that matches the query better than any code still cannot take the
        code's tokens, because it is drawing from a different pot."""
        long_prose = [
            _chunk("README.md", "How the engine is built. " * 60, policy.MARKDOWN, i)
            for i in range(1, 8)
        ]
        b = builder(QUESTION_ANSWERING, token_budget=1200, prose=long_prose)

        context = await b.build(SECTION, "architecture")

        assert context.retrieved_blocks, "code was entirely displaced by prose"
        from codelith.llm.context_manager import count_text_tokens

        prose_tokens = sum(count_text_tokens(b_) for b_ in context.prose_blocks)
        assert prose_tokens <= b.token_budget - b.code_budget + 1

    def test_the_code_budget_is_derived_from_the_policy(self) -> None:
        b = SectionContextBuilder(
            db=None, kb_id=1, project_id=1,  # type: ignore[arg-type]
            token_budget=1000, retrieval_policy=QUESTION_ANSWERING,
        )

        assert b.code_budget == 700

    def test_a_code_only_policy_reserves_everything(self) -> None:
        b = SectionContextBuilder(
            db=None, kb_id=1, project_id=1, token_budget=1000  # type: ignore[arg-type]
        )

        assert b.code_budget == 1000
        assert b.policy.prose_share == 0.0


class TestProseArrivesLabelled:
    async def test_prose_is_separated_from_source(self, builder) -> None:
        """Kept in its own list so it cannot be mistaken for retrieved source by any
        code that walks the context."""
        b = builder(QUESTION_ANSWERING)

        context = await b.build(SECTION, "architecture")

        assert context.prose_blocks
        assert all("unverified" in block for block in context.prose_blocks)

    async def test_the_rendered_section_says_it_is_unverified(self, builder) -> None:
        b = builder(QUESTION_ANSWERING)

        rendered = (await b.build(SECTION, "architecture")).render()

        assert "UNVERIFIED" in rendered
        assert "never as evidence" in rendered

    async def test_docstrings_outrank_readmes(self, builder) -> None:
        """A docstring ships in the same file as the code and is reviewed in the same
        diff. A root README can be years older than everything it documents."""
        b = builder(QUESTION_ANSWERING, token_budget=2000)

        context = await b.build(SECTION, "architecture")

        assert context.prose_blocks
        assert "docstring" in context.prose_blocks[0]

    async def test_prose_is_dropped_first_when_trimming(self, builder) -> None:
        """It is the least certain material in the bundle and the only kind that can
        actively mislead, so it goes before any source does."""
        b = builder(QUESTION_ANSWERING, token_budget=2000)
        context = await b.build(SECTION, "architecture")
        context.source_blocks = ["--- app/x.py:1-2 ---\n```python\nx = 1\n```"]
        context.prose_blocks = ["--- README.md:1-2 (markdown, unverified) ---\nwords " * 200]

        b.token_budget = 60
        b._trim(context)

        assert context.prose_blocks == []
        assert context.source_blocks


class TestPolicyValidation:
    def test_prose_cannot_be_evidence_when_it_is_not_retrieved(self) -> None:
        with pytest.raises(ValueError):
            RetrievalPolicy(name="bad", allow_prose=False, prose_is_evidence=True)

    def test_a_zero_code_share_is_refused(self) -> None:
        """A policy where code is reserved nothing is not a policy, it is a bug."""
        with pytest.raises(ValueError):
            RetrievalPolicy(name="bad", allow_prose=True, code_share=0.0)

    def test_neither_shipped_policy_treats_prose_as_evidence(self) -> None:
        assert DOCS_GENERATION.prose_is_evidence is False
        assert QUESTION_ANSWERING.prose_is_evidence is False


class TestProseChunking:
    def test_markdown_is_split_on_its_headings(self) -> None:
        chunks = chunk_prose([SourceFile(path="README.md", content=README)])

        # Three headings, and this README opens with one — so no preamble section.
        assert len(chunks) == 3
        assert all(c["chunk_type"] == policy.MARKDOWN for c in chunks)
        assert any("Deployment" in c["content"] for c in chunks)
        # Each section is self-contained: a chunk about deployment does not carry
        # the architecture section with it.
        deployment = next(c for c in chunks if "Deployment" in c["content"])
        assert "Architecture" not in deployment["content"]

    def test_a_heading_inside_a_fence_is_not_a_split(self) -> None:
        """A README documenting shell commands is full of `#`. Splitting on those
        shreds every code sample in it."""
        content = "# Title\n\n```bash\n# install\npip install x\n# run\nrun it\n```\n"

        chunks = chunk_prose([SourceFile(path="README.md", content=content)])

        assert len(chunks) == 1

    def test_text_before_the_first_heading_is_kept(self) -> None:
        """Often the entire point of a README."""
        content = "This project does the thing.\n\n## Usage\n\nRun it.\n"

        chunks = chunk_prose([SourceFile(path="README.md", content=content)])

        assert "does the thing" in chunks[0]["content"]

    def test_a_substantial_docstring_becomes_a_prose_chunk(self) -> None:
        chunks = chunk_files([SourceFile(path="app/db/session.py", content=CODE_FILE)])
        docstrings = [c for c in chunks if c["chunk_type"] == policy.DOCSTRING]

        assert docstrings
        assert any("make_engine" in c["content"] for c in docstrings)

    def test_a_one_line_docstring_is_not_indexed_as_prose(self) -> None:
        """A label, not intent. Indexing these dilutes the prose pool with noise."""
        source = 'def go():\n    """Do it."""\n    return 1\n'

        chunks = chunk_files([SourceFile(path="app/x.py", content=source)])

        assert [c for c in chunks if c["chunk_type"] == policy.DOCSTRING] == []

    def test_code_chunks_still_carry_the_code_type(self) -> None:
        """The whole policy keys on this field. A regression here silently disables
        every guarantee above."""
        chunks = chunk_files([SourceFile(path="app/db/session.py", content=CODE_FILE)])

        assert any(c["chunk_type"] == policy.CODE for c in chunks)

    def test_prose_chunks_report_the_lines_they_hold(self) -> None:
        chunks = chunk_prose([SourceFile(path="README.md", content=README)])

        for chunk in chunks:
            assert chunk["start_line"] >= 1
            assert chunk["end_line"] >= chunk["start_line"]
