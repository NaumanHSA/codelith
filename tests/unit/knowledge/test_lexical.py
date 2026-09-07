"""
Finding code by its name.

Retrieval was one cosine search, and that is the wrong instrument for an identifier.
Measured against the real Watchtower knowledge base, searching `update_with_detection`
returned six chunks and not one was the file declaring it, so the model reported the
function did not exist. These are the query shapes a reader actually types, and every
one of them has to reach the same symbol.
"""

import pytest

from codelith.knowledge import lexical


class TestStemming:
    """
    The forms have to meet in the middle.

    The first attempt stripped `es` in one pass, which took `updates` to `updat` while
    `update` stayed whole. They still disagreed, the overlap route saw one shared word
    instead of two, and "what updates a track" found nothing.
    """

    @pytest.mark.parametrize(
        "a, b",
        [
            ("updates", "update"),
            ("updating", "update"),
            ("updated", "update"),
            ("detections", "detection"),
            ("handles", "handle"),
            ("classes", "class"),
        ],
    )
    def test_inflections_reduce_to_one_key(self, a, b):
        assert lexical._stem(a) == lexical._stem(b)

    def test_it_does_not_collapse_words_that_differ(self):
        """`router` and `route` are two different things in this vocabulary, and a
        real stemmer would merge them."""
        assert lexical._stem("router") != lexical._stem("route")

    def test_a_double_s_is_not_a_plural(self):
        assert lexical._stem("class") == "class"


class TestFolding:
    @pytest.mark.parametrize(
        "text",
        ["update_with_detection", "updateWithDetection", "UpdateWithDetection", "update with detection"],
    )
    def test_every_style_of_the_same_name_folds_alike(self, text):
        assert lexical.fold(text) == "updatewithdetection"

    def test_words_split_on_case_and_underscore(self):
        assert lexical.words("FaceTrack.update_with_detection") == [
            "face", "track", "update", "with", "detection",
        ]


class TestTellingANameFromAQuestion:
    """
    How much a one-word match is worth depends on what surrounds it.

    In "what updates a track with a detection", `track` is a real symbol, and treating
    it as the thing being asked about outranked the method the sentence describes.
    """

    @pytest.mark.parametrize(
        "query", ["what updates a track with a detection", "how is the engine started"]
    )
    def test_a_question_is_a_sentence(self, query):
        assert lexical._is_sentence(query) is True

    @pytest.mark.parametrize(
        "query", ["update_with_detection", "FaceTrack.update_with_detection", "updateWithDetection"],
    )
    def test_a_quoted_name_is_not(self, query):
        """`with` inside an identifier is part of a name, not grammar."""
        assert lexical._is_sentence(query) is False


class TestQueryTerms:
    def test_stopwords_go(self):
        assert set(lexical.query_terms("what does the engine do")) == {"engine"}

    def test_the_specific_word_comes_first(self):
        """Longest first, because it is the one that identifies the symbol."""
        assert lexical.query_terms("what updates a track with a detection")[0] == "detection"


@pytest.mark.asyncio
class TestFindingSymbols:
    """
    Against a small stand-in knowledge base, so the shapes are checked without a
    repository behind them.
    """

    @pytest.fixture
    async def kb(self):
        """An in-memory knowledge base holding nothing but symbols, which is all this
        reads. No repository, no embeddings, no model."""
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        import codelith.models  # noqa: F401  — registers the tables
        from codelith.db.base import Base
        from codelith.models.graph import GraphSymbol

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)()

        rows = [
            ("worker/engine/models.py", "FaceTrack.update_with_detection", "update_with_detection", "method", 65),
            ("worker/engine/yunet.py", "ObjectTracker.update", "update", "method", 311),
            ("controller/repositories/streams_repo.py", "StreamsRepo.update", "update", "method", 33),
            ("worker/engine/models.py", "DetectorParams.track", "track", "attribute", 180),
            ("controller/routers/broadcast.py", "build_received_detection", "build_received_detection", "function", 237),
        ]
        for path, qname, name, kind, line in rows:
            session.add(
                GraphSymbol(
                    project_id=1, kb_id=1, path=path, qname=qname,
                    name=name, kind=kind, line=line, end_line=line + 10,
                )
            )
        await session.commit()
        yield session
        await session.close()
        await engine.dispose()

    async def _names(self, db, query):
        hits = await lexical.find_symbols(db, 1, 1, query)
        return [h.name for h in hits]

    async def test_the_exact_name(self, kb):
        assert (await self._names(kb, "update_with_detection"))[0] == "update_with_detection"

    async def test_qualified_by_its_class(self, kb):
        assert (await self._names(kb, "FaceTrack.update_with_detection"))[0] == "update_with_detection"

    async def test_written_in_another_style(self, kb):
        assert (await self._names(kb, "updateWithDetection"))[0] == "update_with_detection"

    @pytest.mark.parametrize(
        "typo",
        ["update_with_detecton", "update_wiht_detection", "update_with_detecttion"],
    )
    async def test_misspelled(self, kb, typo):
        """
        The case that exposed the gating bug: `update` is itself a symbol here, so an
        earlier version found *something*, concluded the search had succeeded, and
        never chased the misspelling.
        """
        assert (await self._names(kb, typo))[0] == "update_with_detection"

    async def test_described_rather_than_named(self, kb):
        assert "update_with_detection" in await self._names(
            kb, "what updates a track with a detection"
        )

    async def test_a_one_word_symbol_does_not_win_a_sentence(self, kb):
        """`track` is a real symbol and the question mentions it, but the question is
        about something else."""
        names = await self._names(kb, "what updates a track with a detection")
        assert names.index("update_with_detection") < names.index("track")

    async def test_an_unrelated_question_finds_nothing(self, kb):
        assert await self._names(kb, "how are database migrations applied") == []

    async def test_a_symbol_in_another_knowledge_base_is_not_returned(self, kb):
        """Scoping, so a re-analysis cannot leak the previous reading."""
        assert await lexical.find_symbols(kb, 999, 1, "update_with_detection") == []
