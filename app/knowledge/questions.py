"""
Routing a free-form question to the right kind of lookup.

`SectionContextBuilder` answers *"give me evidence for this known section"*. A
question is a different shape: nobody has decided yet what the answer is about, so
something has to choose between the four stores before any of them is queried.

| Signal in the question | Store |
|---|---|
| a path, or a symbol we know | the graph — callers, imports, blast radius |
| "what calls", "what breaks if" | the graph, traversed |
| "where is X", "what does it talk to" | entities, by kind |
| "how does X work" | narratives, then code |
| anything | code chunks, semantically |

**Routed by a model, checked against the knowledge base.** The rule-based router
below was built first, deliberately, so K1–K3 could be measured without a model
confounding the result — and it earned its keep by exposing three routing defects.
But it could never survive a codebase nobody has seen: the code and the phrasing are
both unbounded, and "which modules would I need to touch if I refactored the
executor" matches no hand-written trigger.

So `LLMQuestionPlanner` is the router, and the rules are its fallback. The model
proposes; the knowledge base disposes — every field it returns is intersected with
what actually exists before anything is queried, so a hallucinated symbol costs one
dropped list entry rather than a traversal after something imaginary.

**This returns evidence, not an answer.** No synthesis, no chat, no model call in the
retrieval path. What comes back is what a future agent *would* have been given, which
is exactly what has to be judged before that agent is worth writing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge import artefacts
from app.knowledge.narratives import topics_for_doc_type
from app.knowledge.policy import QUESTION_ANSWERING, PROSE_TYPES
from app.knowledge.retrieval import SectionContextBuilder
from app.memory.graph_store import GraphStore

logger = structlog.get_logger(__name__)

#: Tokens that *look like code* rather than English: backticked, CamelCase, dotted,
#: or containing an underscore.
#:
#: Matching bare lowercase words instead was measurably worse. "what calls the tool
#: registry" matched the symbol `tool`, because `tool` is both an ordinary English
#: word and a real identifier — so the router chased a symbol the asker never named
#: and the traversal returned nothing. Requiring a shape English does not have costs
#: nothing: people naming a symbol in a question write `ToolPool.get` or
#: `register_tool_factory`, not "tool".
_IDENTIFIER = re.compile(
    r"`([^`]+)`"                                   # `anything backticked`
    r"|\b([A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*(?:\.\w+)*)\b"   # CamelCase, optionally dotted
    r"|\b(\w+\.\w+(?:\.\w+)*)\b"                   # dotted.path
    r"|\b(\w*_\w+)\b"                              # snake_case
)

#: `app/db/session.py`, `src/main.go`
_PATH = re.compile(r"\b([\w./-]+/[\w.-]+\.\w{1,5})\b")

#: Question shapes that mean "traverse", not "search". These are the questions vector
#: search cannot answer at all — no embedding of a function body encodes its callers.
_GRAPH_PHRASES = (
    "what calls", "who calls", "what uses", "who uses", "what depends",
    "what breaks", "what would break", "impact of", "blast radius",
    "what imports", "who imports", "callers of", "dependents of",
)

#: Phrases that name an entity kind directly. The KB already holds these as facts, so
#: answering from them beats retrieving code and hoping the answer is visible in it.
_ENTITY_PHRASES: dict[str, tuple[str, ...]] = {
    "datastore": ("where is data stored", "what database", "data stored", "datastore",
                  "storage", "persisted", "where does it store"),
    # "talk to", not "what does it talk to": the natural phrasing is "what *external
    # services* does it talk to", and the longer pattern missed it while `service`
    # matched — so the question about integrations returned the component list.
    "external_api": ("talk to", "external", "third party", "third-party", "integrations",
                     "which apis", "outbound", "upstream"),
    "scheduled_task": ("what runs on a schedule", "scheduled", "cron", "periodic",
                       "background job", "recurring"),
    "route": ("what endpoints", "which routes", "http api", "rest api", "endpoints"),
    "env_var": ("environment variable", "env var", "configuration", "configured", "settings"),
    "entrypoint": ("entry point", "entrypoint", "how do i run", "how to start", "how is it started"),
    "cli_command": ("cli", "command line", "commands"),
    "infra_resource": ("deployed", "deployment", "docker", "kubernetes", "infrastructure"),
    "event": ("events", "queue", "pub/sub", "published", "message"),
    "service": ("components", "services", "moving parts"),
}

#: Narrative topics worth offering when a question is about how something works.
_HOW_PHRASES = ("how does", "how do", "how is", "what happens when", "explain", "walk me through")


@dataclass(slots=True)
class Evidence:
    """
    One piece of retrieved material, and why it is here.

    `why` exists for the inspector. A retrieval layer that cannot explain a result
    cannot be debugged, and the whole purpose of this phase is finding out where
    K1–K3 fall short.
    """

    kind: str
    title: str
    body: str
    why: str
    #: Lower is closer for vector results; None where ranking does not apply.
    score: float | None = None

    def render(self) -> str:
        return f"--- [{self.kind}] {self.title} ---\n{self.body}"


@dataclass(slots=True)
class QuestionPlan:
    """What the router decided, before anything was fetched."""

    question: str
    intents: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    entity_kinds: list[str] = field(default_factory=list)
    #: Narrative topics chosen for this question. Empty under the rule-based
    #: router, which had no way to pick one — see `_add_narratives`.
    narrative_topics: list[str] = field(default_factory=list)
    #: The question rewritten into the vocabulary the code uses. The thing a
    #: phrase table structurally cannot produce.
    search_queries: list[str] = field(default_factory=list)
    #: 'llm' or 'rules'. Recorded because a fallback route and a chosen one are
    #: not equally trustworthy, and the inspector must not blur them.
    routed_by: str = "rules"
    reasoning: str = ""
    #: True when `paths` came from semantic search rather than from the question.
    #: Recorded so evidence can say honestly how it was reached — a traversal from
    #: an inferred anchor is a weaker claim than one from a path the asker named.
    anchored: bool = False

    def describe(self) -> str:
        bits = [f"via={self.routed_by}", f"intents={self.intents or ['semantic']}"]
        if self.anchored:
            bits.append("(paths inferred by search)")
        if self.symbols:
            bits.append(f"symbols={self.symbols}")
        if self.paths:
            bits.append(f"paths={self.paths}")
        if self.entity_kinds:
            bits.append(f"entity_kinds={self.entity_kinds}")
        if self.narrative_topics:
            bits.append(f"topics={self.narrative_topics}")
        if self.search_queries:
            bits.append(f"queries={self.search_queries}")
        return "  ".join(bits)


@dataclass(slots=True)
class EvidenceBundle:
    """Everything the question retrieved, in the order a reader should see it."""

    plan: QuestionPlan
    items: list[Evidence] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Evidence]:
        return [i for i in self.items if i.kind == kind]

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.items:
            out[item.kind] = out.get(item.kind, 0) + 1
        return out

    def render(self) -> str:
        return "\n\n".join(i.render() for i in self.items) or "(no evidence found)"


@dataclass(frozen=True, slots=True)
class KBVocabulary:
    """
    What this knowledge base actually contains.

    Handed to the model so it chooses from a real menu, and used afterwards to throw
    away anything it invented. Both directions matter: without the menu it guesses at
    a schema, and without the check its guesses are believed.
    """

    entity_kinds: frozenset[str] = frozenset()
    narrative_topics: frozenset[str] = frozenset()
    symbols: frozenset[str] = frozenset()
    paths: frozenset[str] = frozenset()
    modules: tuple[str, ...] = ()


def plan_question(question: str, known_symbols: set[str] | None = None) -> QuestionPlan:
    """
    Decide what a question is about, without touching a database or a model.

    Kept as the fallback for `LLMQuestionPlanner`, and as the baseline any change to
    the model-driven router is compared against. A question that returns nothing
    because a model timed out is worse than one routed by a crude rule.
    """
    lowered = question.lower()
    plan = QuestionPlan(question=question)

    plan.paths = list(dict.fromkeys(_PATH.findall(question)))

    if any(phrase in lowered for phrase in _GRAPH_PHRASES):
        plan.intents.append("graph")

    for kind, phrases in _ENTITY_PHRASES.items():
        # Whole words, both ends. Naive substring matching routed "what imports the
        # LLM client" to `cli_command` because "client" contains "cli"; a leading
        # boundary alone was not enough, since "client" *starts* with it.
        if any(re.search(rf"\b{re.escape(phrase)}\b", lowered) for phrase in phrases):
            plan.entity_kinds.append(kind)
    if plan.entity_kinds:
        plan.intents.append("entities")

    if any(phrase in lowered for phrase in _HOW_PHRASES):
        plan.intents.append("narrative")

    # Identifiers are only worth chasing if we actually know them — an unrecognised
    # one is a typo or a concept, and either way a symbol lookup will find nothing.
    if known_symbols:
        candidates: set[str] = set()
        for groups in _IDENTIFIER.findall(question):
            for token in groups:
                if not token:
                    continue
                candidates.add(token)
                # `ToolPool.get` should also try `get`: the graph stores methods under
                # their bare name as well as qualified.
                if "." in token:
                    candidates.add(token.rsplit(".", 1)[-1])
        plan.symbols = sorted(c for c in candidates if c in known_symbols)[:5]
        if plan.symbols and "graph" not in plan.intents:
            plan.intents.append("graph")

    if plan.paths and "graph" not in plan.intents:
        plan.intents.append("graph")

    # Semantic search always runs. Routing decides what to add, never what to remove:
    # a misrouted question should return more than it needs, not less.
    plan.intents.append("semantic")
    return plan


#: Intents the rest of this module knows how to act on. A model naming anything else
#: is proposing a store that does not exist.
_KNOWN_INTENTS = frozenset({"semantic", "entities", "narrative", "graph"})

#: Entity kinds acted on, and the total rows they may contribute between them.
#: Facts are the densest evidence we hold; past this they stop being evidence and
#: start being a list.
_MAX_ENTITY_KINDS = 4
_MAX_ENTITIES = 24


class LLMQuestionPlanner:
    """
    Routing by model, validated against the knowledge base.

    The phrase tables could not survive a codebase nobody had seen: both the code and
    the phrasing are unbounded, and "which modules would I need to touch if I
    refactored the executor" matches no list of hand-written triggers.

    **The model proposes; the knowledge base disposes.** Every field it returns is
    intersected with what actually exists before anything is queried, so a
    hallucinated symbol is one dropped list entry rather than a traversal after
    something imaginary. That is what makes it safe to give a small local model this
    much say.

    Falls back to `plan_question` on any failure. A question that returns nothing
    because a model timed out is worse than one routed by a crude rule.
    """

    def __init__(self, vocabulary: KBVocabulary, project_name: str = "this repository") -> None:
        self.vocabulary = vocabulary
        self.project_name = project_name

    async def plan(self, question: str) -> QuestionPlan:
        raw = await self._ask(question)
        if raw is None:
            logger.info("question_route_fallback", question=question[:80])
            plan = plan_question(question, known_symbols=set(self.vocabulary.symbols))
            plan.routed_by = "rules"
            return plan
        return self._validate(question, raw)

    async def _ask(self, question: str) -> dict | None:
        from app.llm.client import chat_completion
        from app.llm.prompts.question_prompts import ROUTE_QUESTION
        from app.llm.router import select_spec

        messages = ROUTE_QUESTION.render(
            project_name=self.project_name,
            question=question,
            entity_kinds=", ".join(sorted(self.vocabulary.entity_kinds)) or "(none)",
            narrative_topics=", ".join(sorted(self.vocabulary.narrative_topics)) or "(none)",
            modules=", ".join(self.vocabulary.modules[:25]) or "(none)",
        )
        try:
            # `plan`, not `classify`, so this runs on the quality tier. Measured on
            # five questions against neurosurfer: the fast tier (a 1.2B local model)
            # answered `datastore` for four of them regardless of what was asked —
            # anchoring on one item of the offered list rather than reading the
            # question. The quality tier returned `external_api, env_var, dependency`
            # with topic `integrations` for the integrations question and
            # `route, request_lifecycle` for the endpoints one.
            #
            # It is one small call, and it decides which stores are consulted at all.
            # Routing badly is not cheaper than routing well; it just fails later.
            raw = await chat_completion(messages, spec=select_spec("plan"))
        except Exception as exc:
            logger.warning("question_route_call_failed", error=str(exc))
            return None

        try:
            return json.loads(_extract_json(raw))
        except (json.JSONDecodeError, ValueError):
            logger.warning("question_route_unparseable", raw=(raw or "")[:200])
            return None

    def _validate(self, question: str, raw: dict) -> QuestionPlan:
        """
        Keep only what exists. Everything here is an intersection, deliberately.

        A model that invents `entity_kinds: ["message_queue"]` on a knowledge base
        with no such kind should cost one empty list, not a query for a kind the
        schema has never held.
        """
        plan = QuestionPlan(question=question, routed_by="llm")
        vocab = self.vocabulary

        plan.intents = [i for i in _as_list(raw.get("intents")) if i in _KNOWN_INTENTS]
        # Semantic is not optional. A model that omits it has removed the only store
        # that answers when every other route misses.
        if "semantic" not in plan.intents:
            plan.intents.append("semantic")

        plan.entity_kinds = [k for k in _as_list(raw.get("entity_kinds")) if k in vocab.entity_kinds]
        if plan.entity_kinds and "entities" not in plan.intents:
            plan.intents.append("entities")

        plan.narrative_topics = [
            t for t in _as_list(raw.get("narrative_topics")) if t in vocab.narrative_topics
        ]
        if plan.narrative_topics and "narrative" not in plan.intents:
            plan.intents.append("narrative")

        plan.symbols = [s for s in _as_list(raw.get("symbols")) if s in vocab.symbols][:5]
        plan.paths = [p for p in _as_list(raw.get("paths")) if p in vocab.paths][:5]
        if (plan.symbols or plan.paths) and "graph" not in plan.intents:
            plan.intents.append("graph")

        # The query rewrite. Not validated against anything — it is a search string,
        # not a claim about the repository, and a bad one costs a poor ranking rather
        # than a wrong fact.
        plan.search_queries = [q for q in _as_list(raw.get("search_queries")) if q][:3]
        plan.reasoning = str(raw.get("reasoning") or "")[:300]
        return plan


def _as_list(value) -> list[str]:
    """Whatever the model returned, as a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v).strip() for v in value if isinstance(v, str | int | float) and str(v).strip()]
    return []


def _extract_json(raw: str) -> str:
    """Strip fences and surrounding prose. Mirrors `BaseAgent._extract_json`."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    if "```" in raw:
        raw = raw.split("```")[0]
    if match := re.search(r"[{\[]", raw):
        start = match.start()
        end = max(raw.rfind("}"), raw.rfind("]")) + 1
        if end > start:
            raw = raw[start:end]
    return raw.strip()


class QuestionRouter:
    """
    Assembles evidence for a free-form question.

    Deliberately not an agent: no model is called anywhere in here. It is the input
    an agent would receive, exposed so that input can be judged first.
    """

    def __init__(
        self,
        db: AsyncSession,
        kb_id: int,
        project_id: int,
        use_llm: bool = True,
        project_name: str = "this repository",
    ) -> None:
        self.db = db
        self.kb_id = kb_id
        self.project_id = project_id
        # Rules remain reachable: they are the fallback when a model is
        # unavailable, and the baseline the model-driven router is compared to.
        self.use_llm = use_llm
        self.project_name = project_name
        self.repos = KnowledgeRepositories.for_session(db)

    async def gather(self, question: str, *, token_budget: int = 6000) -> EvidenceBundle:
        if self.use_llm:
            vocabulary = await self.vocabulary()
            plan = await LLMQuestionPlanner(vocabulary, self.project_name).plan(question)
        else:
            plan = plan_question(question, known_symbols=await self._known_symbols())
        bundle = EvidenceBundle(plan=plan)

        if "entities" in plan.intents:
            await self._add_entities(bundle)
            await self._add_artefact_profile(bundle)
        if "narrative" in plan.intents:
            await self._add_narratives(bundle)

        # Semantic first when a traversal is wanted but nothing traversable was
        # named. Measured on the question set: all three of "what calls the tool
        # registry", "what breaks if I change the config module" and "what imports
        # the LLM client" routed to the graph and returned no graph evidence at all,
        # because each names a concept in English rather than a symbol or a path.
        # The graph was fine; the router simply had no anchor to start from. Letting
        # semantic search supply one is what connects English to a traversal.
        semantic = await self._semantic(
            question, bundle.plan.paths, token_budget, plan.search_queries
        )
        if "graph" in plan.intents:
            if not plan.paths and not plan.symbols:
                plan.paths = _anchor_paths(semantic["code"])
                plan.anchored = bool(plan.paths)
            await self._add_graph(bundle)
        bundle.items.extend(semantic["code"] + semantic["prose"])

        logger.info(
            "question_routed",
            kb_id=self.kb_id,
            intents=plan.intents,
            counts=bundle.counts,
        )
        return bundle

    # ── Stores ────────────────────────────────────────────────────────────────

    async def vocabulary(self) -> KBVocabulary:
        """
        What this knowledge base holds, for the model to choose from and be checked
        against.

        Only kinds and topics that are actually *present* are offered. A model told
        `scheduled_task` exists on a repository with none will route questions to an
        empty store and look like retrieval failed.
        """
        kinds = await self.repos.entities.kind_breakdown(self.kb_id)
        topics = await self.repos.narratives.topics_present(self.kb_id)
        modules = await self.repos.modules.list_by_kb(self.kb_id)

        symbols: set[str] = set()
        paths: set[str] = set()
        for module in modules:
            paths.update(module.files_json or [])
            for symbol in module.symbols_json or []:
                if name := symbol.get("name"):
                    symbols.add(name)

        return KBVocabulary(
            entity_kinds=frozenset(k for k, n in kinds.items() if n),
            narrative_topics=frozenset(str(t) for t in topics),
            symbols=frozenset(symbols),
            paths=frozenset(paths),
            # Ordered by size: the biggest modules are the ones worth naming to a
            # router with a limited window.
            modules=tuple(m.name for m in modules[:25]),
        )

    async def _known_symbols(self) -> set[str]:
        """
        Symbol names in this KB, so an identifier in a question can be recognised.

        Read from `kb_modules.symbols_json` rather than the graph: it is one query
        against Postgres, and it works when Neo4j is unreachable.
        """
        out: set[str] = set()
        for module in await self.repos.modules.list_by_kb(self.kb_id):
            for symbol in module.symbols_json or []:
                if name := symbol.get("name"):
                    out.add(name)
        return out

    async def _add_artefact_profile(self, bundle: EvidenceBundle) -> None:
        """
        What conventional files this repository has, and which it does not.

        Only for questions already routed at the file-shaped kinds — deployment,
        configuration, how to run it. On a question about datastores this would be
        noise, and the entity budget is tight enough already.

        Absence is why it exists. Retrieval returns what exists, so a question about
        deployment gets whatever deployment-ish material is nearby and nothing can
        contradict it: asked how neurosurfer is deployed, an answer described a
        container image the repository does not build, from documentation that
        recommends one. This is the evidence that says so.
        """
        wanted = set(bundle.plan.entity_kinds) & set(artefacts.FILE_ENTITY_KINDS)
        if not wanted:
            return

        paths: list[str] = []
        for kind in artefacts.FILE_ENTITY_KINDS:
            rows = await self.repos.entities.list_by_kind(self.kb_id, kind, limit=100)
            paths.extend(row.source_path or row.name for row in rows)

        present, absent = artefacts.profile(paths)
        bundle.items.append(Evidence(
            kind="entity",
            title="repository artefacts",
            body=artefacts.render(present, absent),
            why="question is about how the repository is built, run or configured",
        ))

    async def _add_entities(self, bundle: EvidenceBundle) -> None:
        """
        Facts, bounded.

        The router is told to prefer including a store over excluding one, which is
        right for *coverage* and wrong left unbounded: asked what the system talks
        to, it named six kinds and 25 rows each came back as 69 entities, burying
        the code they were meant to support. The budget is shared across whatever
        kinds were chosen, so more kinds means fewer of each rather than more of
        everything.
        """
        kinds = bundle.plan.entity_kinds[:_MAX_ENTITY_KINDS]
        if not kinds:
            return
        per_kind = max(3, _MAX_ENTITIES // len(kinds))

        for kind in kinds:
            rows = await self.repos.entities.list_by_kind(self.kb_id, kind, limit=per_kind)
            for row in rows:
                where = f"{row.source_path}:{row.source_line}" if row.source_path else "—"
                bundle.items.append(Evidence(
                    kind="entity",
                    title=f"{row.kind}: {row.name}",
                    body=f"{row.data_json or {}}\n  at {where}",
                    why=f"question names the '{kind}' concept",
                ))

    async def _add_narratives(self, bundle: EvidenceBundle) -> None:
        """
        The narratives this question is about.

        Previously this ignored the question entirely and returned the first three
        *architecture* topics whatever was asked, so "how does authentication work"
        and "what happens when a job fails" got identical evidence — while `auth`
        and `error_handling` sat unread in the same knowledge base. Choosing a
        topic is natural-language work, which is why it is the model's job.
        """
        topics = bundle.plan.narrative_topics or [
            str(t) for t in topics_for_doc_type("architecture")[:3]
        ]
        for topic in topics[:4]:
            narrative = await self.repos.narratives.get(self.kb_id, topic)
            if narrative:
                bundle.items.append(Evidence(
                    kind="narrative",
                    title=topic,
                    body=narrative.content_md[:1500],
                    why=(
                        "the router chose this topic for the question"
                        if bundle.plan.narrative_topics
                        else "default topic — the router named none"
                    ),
                ))

    async def _add_graph(self, bundle: EvidenceBundle) -> None:
        """
        Traversals. The questions vector search structurally cannot answer.

        Non-fatal: Neo4j being down degrades the bundle rather than failing it, in
        the same way the analysis pipeline degrades.
        """
        try:
            async with GraphStore() as graph:
                for path in bundle.plan.paths:
                    dependents = await graph.get_dependents(self.project_id, path)
                    radius = await graph.get_blast_radius(self.project_id, path)
                    if dependents or radius:
                        bundle.items.append(Evidence(
                            kind="graph",
                            title=f"impact of {path}",
                            body=(
                                f"imported directly by {len(dependents)} file(s): "
                                f"{', '.join(dependents[:8]) or '—'}\n"
                                f"reachable within 3 hops: {len(radius)} file(s)"
                            ),
                            why=(
                                "search identified this file; the graph answered "
                                "the traversal"
                                if bundle.plan.anchored
                                else "question names a file path"
                            ),
                        ))
                for symbol in bundle.plan.symbols:
                    callers = await graph.get_callers(self.project_id, symbol)
                    if callers:
                        bundle.items.append(Evidence(
                            kind="graph",
                            title=f"callers of {symbol}",
                            body="\n".join(f"  {c['file']} :: {c['caller']}" for c in callers[:12]),
                            why="question names a symbol this KB defines",
                        ))
        except Exception as exc:  # pragma: no cover - Neo4j optional
            logger.warning("question_graph_unavailable", error=str(exc))

    async def _semantic(
        self,
        question: str,
        key_files: list[str],
        token_budget: int,
        queries: list[str] | None = None,
    ) -> dict[str, list[Evidence]]:
        """
        Code and prose, under the question-answering policy.

        Returned rather than appended, so the caller can use the code hits to anchor
        a graph traversal before deciding where they belong in the bundle.

        Prose is retrieved as a *router*: it is here to name files worth reading, and
        arrives labelled unverified so nothing downstream can mistake it for a
        citation. See `app/knowledge/policy.py`.
        """
        builder = SectionContextBuilder(
            db=self.db,
            kb_id=self.kb_id,
            project_id=self.project_id,
            token_budget=token_budget,
            retrieval_policy=QUESTION_ANSWERING,
        )
        # The rewritten queries, when the router produced them. "how do I run this
        # locally" is a poor embedding query; "uvicorn entrypoint, docker compose
        # services, Makefile dev target" is a good one, and moving the question into
        # the vocabulary the *code* uses is most of what makes retrieval work.
        focus = "; ".join(queries) if queries else question
        context = await builder.build(
            {"name": question, "focus": focus, "key_files": key_files},
            "architecture",
        )
        return {
            "code": [
                Evidence(kind="code", title=_title_of(b), body=b, why="semantic match")
                for b in context.source_blocks + context.retrieved_blocks
            ],
            "prose": [
                Evidence(
                    kind="prose",
                    title=_title_of(b),
                    body=b,
                    why="prose — use to locate code, never as evidence",
                )
                for b in context.prose_blocks
            ],
        }


#: Anchors taken from semantic hits. Two, not ten: a blast radius is only meaningful
#: for a file the question is actually about, and the third-best guess rarely is.
_MAX_ANCHORS = 2


def _anchor_paths(code: list[Evidence]) -> list[str]:
    """
    File paths from the best semantic matches, to traverse from.

    This is how a question phrased in English — "what breaks if I change the config
    module" — reaches the graph at all. Vector search identifies *which* file is
    meant; the graph then answers the part vector search cannot.
    """
    paths: list[str] = []
    for item in code:
        path = item.title.split(":")[0].strip()
        if path and path not in paths:
            paths.append(path)
        if len(paths) >= _MAX_ANCHORS:
            break
    return paths


def _title_of(block: str) -> str:
    first = block.split("\n", 1)[0]
    return first.strip("- ").strip() or "(block)"


__all__ = [
    "QuestionRouter",
    "QuestionPlan",
    "EvidenceBundle",
    "Evidence",
    "plan_question",
]
