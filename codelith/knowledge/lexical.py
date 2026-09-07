"""
Finding code by its name, which an embedding cannot do.

Retrieval was one cosine search over chunk vectors, and that is the right tool for
*"where is rate limiting handled"* and the wrong one for *"update_with_detection"*. A
bare identifier embeds to its **meaning** — roughly "update, detection" — and lands on
whatever code is semantically about updating detections, which is rarely the file that
actually declares it. Measured against Watchtower: searching `update_with_detection`
returned six chunks and not one of them was `models.py`, where the method is defined.
The model then reported, correctly for what it had been given, that the function did
not exist.

So this is the other half. It never embeds anything; it matches names against
`graph_symbols`, which analysis already built and which stores every symbol with its
file and line. Four ways, strongest first, because a reader will type any of them:

1. **Exactly.** `update_with_detection`, or `FaceTrack.update_with_detection`.
2. **In a different style.** `updateWithDetection` and `update_with_detection` are the
   same name to a person, so both fold to the same key.
3. **Misspelled.** `update_with_detecton` is one edit away and should still find it.
4. **Described.** *"what updates a track with a detection"* shares three words with the
   symbol's own name; that overlap is a real signal, and it costs nothing to use it.

The result is a list of *symbols*, which the caller turns into the chunks that contain
them. Nothing here ranks chunks or talks to a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.graph import GraphSymbol

#: Words that carry no signal in a code question. Deliberately short: dropping too much
#: turns "what does the runner do" into "runner do", and `do` is a real method name.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
    "how", "i", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to",
    "what", "when", "where", "which", "who", "why", "with", "you", "your",
})

#: A token has to be this long before it is worth a fuzzy comparison. Two-character
#: tokens are one edit from hundreds of symbols and match nothing usefully.
_MIN_FUZZY_LEN = 4

#: How close a misspelling has to be. 0.82 accepts one or two edits in a name of
#: ordinary length and rejects words that merely start alike, which was the failure
#: mode at 0.7: `update` matched `upsert`.
_FUZZY_THRESHOLD = 0.82

#: Ceiling on symbols returned. The caller turns each into a chunk, and a query that
#: matches eighty names is a query the vector half should be answering.
_MAX_SYMBOLS = 12

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True, slots=True)
class SymbolHit:
    """One symbol the query named, and how sure we are."""

    path: str
    qname: str
    name: str
    kind: str
    line: int
    score: float
    #: Which of the four routes found it, for the log and for the tests.
    how: str

    @property
    def strong(self) -> bool:
        """Certain enough that the answer is wrong without it."""
        return self.how in {"exact", "normalised"}


def words(text: str) -> list[str]:
    """`FaceTrack.update_with_detection` -> ['face', 'track', 'update', 'with', 'detection']."""
    out: list[str] = []
    for raw in _WORD.findall(text or ""):
        for part in _CAMEL.sub(" ", raw).split():
            out.append(part.lower())
    return out


def fold(text: str) -> str:
    """A style-independent key: case, underscores and separators all removed."""
    return "".join(words(text))


def query_terms(query: str) -> list[str]:
    """
    The words worth searching for, longest first.

    Longest first because the specific word is the one that identifies the symbol:
    in "what does update_with_detection do", `detection` is worth more than `does`.
    """
    seen: dict[str, None] = {}
    for w in words(query):
        if w not in _STOPWORDS and len(w) > 1:
            seen[w] = None
    return sorted(seen, key=len, reverse=True)


def _stem(word: str) -> str:
    """
    Crude, and enough. `updates` and `update` have to reduce to one key, or asking
    "what updates a track" never reaches `update_with_detection`.

    The order matters and the first attempt got it wrong: stripping `es` in one pass
    took `updates` to `updat` while `update` stayed whole, so the two forms still
    disagreed and the overlap route found one word where there were two. What makes
    them meet is peeling in stages and finishing on the silent `e` from both sides.

        updates  -> update -> updat
        update   ->           updat
        updating ->           updat
        classes  -> classe -> class
        class    ->           class   (`ss` is not a plural)

    Deliberately not a real stemmer. This compares one identifier against one
    question, and Porter would fold `router` onto `route`, which in this vocabulary
    are two different things.
    """
    if len(word) > 6 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 5 and word.endswith("ed"):
        word = word[:-2]
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in words(text)}


def _is_sentence(query: str) -> bool:
    """
    Whether this reads as a question rather than a name being quoted.

    The distinction decides how much a one-word match is worth. In *"what updates a
    track with a detection"*, `track` happens to be a real symbol, and treating that
    as the thing being asked about outranked the method the question actually
    describes. In `FaceTrack.update_with_detection` there is nothing but the name, so
    a match on it is the answer.

    Standalone stopwords are the tell: `with` inside an identifier is part of a name,
    `with` on its own is grammar.
    """
    return any(re.sub(r"[^a-z]", "", w.lower()) in _STOPWORDS for w in (query or "").split())


def _identifier_like(query: str) -> list[str]:
    """
    Runs of the query that look like a name somebody is quoting.

    `update_with_detection` and `FaceTrack.update_with_detection` both qualify; an
    English sentence does not, which is what keeps the fuzzy pass off the hot path for
    ordinary questions.
    """
    out = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", query or ""):
        bare = token.rsplit(".", 1)[-1]
        if len(bare) < _MIN_FUZZY_LEN:
            continue
        if "_" in token or "." in token or _CAMEL.search(token) or token.islower():
            out.append(token)
    return out


async def find_symbols(
    db: AsyncSession, kb_id: int, project_id: int, query: str, limit: int = _MAX_SYMBOLS
) -> list[SymbolHit]:
    """
    Symbols the query names, best first.

    Cheap routes run in SQL against the whole table. The fuzzy route needs every name
    in memory, so it only runs when the earlier ones found nothing *and* the query
    actually contains something identifier-shaped — a misspelling is only worth
    hunting for when a name was being typed at all.
    """
    terms = query_terms(query)
    if not terms:
        return []

    scoped = (GraphSymbol.kb_id == kb_id, GraphSymbol.project_id == project_id)
    hits: dict[str, SymbolHit] = {}

    def keep(row, score: float, how: str) -> None:
        key = f"{row.path}:{row.qname}"
        current = hits.get(key)
        if current is None or score > current.score:
            hits[key] = SymbolHit(
                path=row.path, qname=row.qname, name=row.name or row.qname,
                kind=row.kind or "symbol", line=row.line or 1, score=score, how=how,
            )

    # ── 1 and 2: the name, exactly or in another style ────────────────────────
    #
    # Only whole quoted tokens, never the individual words of a sentence. Feeding
    # `terms` in here meant that searching `update_with_detecton` also matched three
    # unrelated methods called `update` at near-perfect score, and they outranked the
    # misspelled name the reader had actually typed.
    quoted = _identifier_like(query)
    sentence = _is_sentence(query)
    folded = {fold(t) for t in quoted}
    folded.discard("")

    def name_score(token: str, base: float) -> float:
        """A one-word hit inside a question is weak evidence; the same hit on its own
        is the whole query."""
        if sentence and len(words(token)) == 1:
            return 0.6
        return base
    if folded:
        rows = (
            await db.execute(
                select(GraphSymbol).where(
                    *scoped,
                    or_(
                        func.lower(GraphSymbol.name).in_(list(folded)),
                        func.lower(GraphSymbol.qname).in_(list(folded)),
                        *[GraphSymbol.name.ilike(t) for t in quoted],
                        *[GraphSymbol.qname.ilike(t) for t in quoted],
                        *[GraphSymbol.qname.ilike(f"%.{t}") for t in quoted],
                    ),
                )
            )
        ).scalars().all()
        typed = {t.lower() for t in quoted}
        for row in rows:
            exact = (row.name or "").lower() in typed or (row.qname or "").lower() in typed
            matched = next(
                (t for t in quoted if fold(t) in {fold(row.name or ""), fold(row.qname or "")}),
                row.name or "",
            )
            keep(
                row,
                name_score(matched, 1.0 if exact else 0.95),
                "exact" if exact else "normalised",
            )

    # **Gated per token, not on whether anything was found at all.**
    #
    # The obvious version of this asked "did the SQL find nothing?" before trying
    # harder, and that was wrong in the exact case it was written for. Searching
    # `update_with_detecton` also yields the word `update`, which *is* a real symbol,
    # so `hits` came back non-empty and the misspelling was never chased. A token is
    # satisfied only when something answering to that name was found.
    satisfied = {fold(h.name) for h in hits.values()} | {fold(h.qname) for h in hits.values()}
    pending = [t for t in quoted if fold(t) not in satisfied]

    # One read, shared by every route below it. A few thousand rows for a large
    # repository, and loading them three times over was the lazy version.
    rows: list | None = None

    async def symbols() -> list:
        nonlocal rows
        if rows is None:
            rows = await _all_symbols(db, scoped)
        return rows

    # ── 2: the same name in another style ─────────────────────────────────────
    # `updateWithDetection` and `update_with_detection` do not compare equal in SQL,
    # because one has underscores and the other has capitals. Folded, they are one
    # string. Only the tokens still unaccounted for are worth the pass.
    if pending:
        wanted = {fold(t) for t in pending}
        for row in await symbols():
            if fold(row.name or "") in wanted or fold(row.qname or "") in wanted:
                keep(row, name_score(row.name or "", 0.95), "normalised")
        satisfied |= {fold(h.name) for h in hits.values()}
        pending = [t for t in pending if fold(t) not in satisfied]

    # ── 3: a misspelling ──────────────────────────────────────────────────────
    if pending:
        for row in await symbols():
            candidate = fold(row.name or "")
            if len(candidate) < _MIN_FUZZY_LEN:
                continue
            for token in pending:
                ratio = SequenceMatcher(None, fold(token), candidate).ratio()
                if ratio >= _FUZZY_THRESHOLD:
                    keep(row, ratio * 0.9, "fuzzy")
                    break

    # ── 4: a description that shares the symbol's own words ───────────────────
    # Always, not only as a fallback: "what updates a track with a detection" should
    # reach the same method as the identifier does, and a symbol that also matched
    # exactly simply keeps its higher score.
    # Stemmed on both sides, because the question says "what **updates** a track" and
    # the method is called `update_with_detection`. Without it the overlap was one
    # word, under the threshold, and the right answer never appeared.
    asked = {_stem(t) for t in terms}
    if asked:
        for row in await symbols():
            own = _stems(row.name or "")
            if len(own) < 2:
                # One-word names ("run", "get") overlap everything and identify nothing.
                continue
            shared = own & asked
            if len(shared) < 2:
                continue
            # Two parts: how much of the *symbol's* name the question accounted for,
            # and how many words agreed at all. A two-word name named in full beats
            # two words of a six-word name, and three agreeing words beat two.
            coverage = len(shared) / len(own)
            weight = min(len(shared), 3) / 3
            keep(row, 0.55 + 0.35 * coverage + 0.10 * weight, "described")

    ranked = sorted(hits.values(), key=lambda h: (-h.score, h.path, h.qname))
    return ranked[:limit]


async def _all_symbols(db: AsyncSession, scoped) -> list:
    """
    Every symbol in the knowledge base.

    A few thousand rows for a large repository, which is nothing to sort in memory and
    the reason the expensive routes above are guarded rather than cached: a chat asks
    one question at a time, and composition never reaches them.
    """
    return list(
        (
            await db.execute(
                select(
                    GraphSymbol.path, GraphSymbol.qname, GraphSymbol.name,
                    GraphSymbol.kind, GraphSymbol.line,
                ).where(*scoped)
            )
        ).all()
    )
