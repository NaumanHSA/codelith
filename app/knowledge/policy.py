"""
What a consumer of the knowledge base is allowed to retrieve.

Docstrings and READMEs carry intent that source code cannot express — *"never
swallow `JobCancelled` in a broad except"* is nowhere in an AST. They are also the
most likely thing in a repository to be wrong. Both are true at once, so the answer
is a policy rather than a yes/no.

**Two consumers, two answers.**

*Documentation generation stays code-only.* Indexing the repository's existing docs
into the generator risks laundering its README into "generated" documentation — the
tool appears to work while having paraphrased the very thing it was hired to
replace. That failure is invisible in the output and fatal to the product's claim.

*Question answering may use prose as a router.* A README is excellent at saying
where to look and unreliable as a citation, so it earns its place by pointing at
code, not by being quoted.

**Priority is structural, never instructional.** A natural-language question is
lexically much closer to a paragraph of prose than to the function implementing it,
so embedding similarity systematically favours prose. "Prefer the code" in a prompt
is a soft constraint that degrades under context pressure and is unreliable on a
small fast-tier model. Instead the budget is split before retrieval runs: prose
cannot crowd out code however well it matches, because it is drawing from a
different pot.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Stored in `code_chunks.chunk_type`. `code` is verbatim source; the rest is prose
#: written by a human, which is what makes it both valuable and untrustworthy.
CODE = "code"
DOCSTRING = "docstring"
MARKDOWN = "markdown"
COMMENT = "comment"

PROSE_TYPES: frozenset[str] = frozenset({DOCSTRING, MARKDOWN, COMMENT})

#: Trust order within prose, most trustworthy first. A docstring ships in the same
#: file as the code it describes and is reviewed in the same diff; a root README can
#: be years older than everything it documents.
PROSE_TRUST: tuple[str, ...] = (DOCSTRING, COMMENT, MARKDOWN)


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    """
    The rules one consumer retrieves under.

    Passed to `SectionContextBuilder` rather than read from settings, because the
    answer genuinely differs per caller — the same index serves both, and a global
    switch would force one consumer to accept the other's risk.
    """

    name: str
    #: Whether prose may be retrieved at all.
    allow_prose: bool = False
    #: Fraction of the token budget reserved for code. Prose competes only for what
    #: is left, so a well-matching README cannot displace the source.
    code_share: float = 1.0
    #: Whether a prose chunk may support a claim on its own. When false it is a
    #: router: worth reading to find the code, never worth quoting as evidence.
    prose_is_evidence: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < self.code_share <= 1.0:
            raise ValueError("code_share must be in (0, 1]")
        if self.prose_is_evidence and not self.allow_prose:
            raise ValueError("prose cannot be evidence when it is not retrieved")

    @property
    def prose_share(self) -> float:
        return 0.0 if not self.allow_prose else 1.0 - self.code_share

    def allows(self, chunk_type: str | None) -> bool:
        return self.allow_prose or (chunk_type or CODE) == CODE


#: Writing a page. The generator never sees the repository's own prose.
DOCS_GENERATION = RetrievalPolicy(name="docs_generation", allow_prose=False, code_share=1.0)

#: Answering a free-form question. Prose is retrieved to find the code, and is
#: labelled unverified wherever it reaches a model.
QUESTION_ANSWERING = RetrievalPolicy(
    name="question_answering",
    allow_prose=True,
    #: Measured intent rather than a round number: leaves prose enough room to route
    #: a question without letting it dominate a context window.
    code_share=0.7,
    prose_is_evidence=False,
)

POLICIES: dict[str, RetrievalPolicy] = {
    p.name: p for p in (DOCS_GENERATION, QUESTION_ANSWERING)
}


__all__ = [
    "RetrievalPolicy",
    "DOCS_GENERATION",
    "QUESTION_ANSWERING",
    "POLICIES",
    "CODE",
    "DOCSTRING",
    "MARKDOWN",
    "COMMENT",
    "PROSE_TYPES",
    "PROSE_TRUST",
]
