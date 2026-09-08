"""
Deciding whether a question is about the codebase at all.

The router chooses which store answers a question and cannot choose none of them, so
"what is the capital of France" came back with the three code chunks whose embeddings
sat closest to a country — and was answered from them, in the voice used for checked
citations.

Two failure modes, and the second is far more expensive:

* **Letting it through** — a general question searched anyway. Costs seconds and
  returns an answer nobody can use.
* **Refusing a real one** — a question about somebody's own code declined because a
  local model did not recognise a word. From the reader's side that is not a
  boundary, it is the product being broken, and they have no way to tell which.

So every uncertain path in here answers `code`, and the cases below are mostly about
holding that: an unreachable model, an unparseable reply, a verdict spelled wrong. The
shortcut is the other half — a question naming anything this repository is made of
never reaches a model, which is what keeps the gate cheap enough to run on every turn.
"""

from __future__ import annotations

import pytest

from codelith.knowledge.scope import CODE, OFF_TOPIC, CodebaseProfile, ScopeGate

#: A repository about elections. Chosen because its subject matter is the thing a
#: naive "is this a programming question" filter gets wrong: here, countries and
#: votes *are* the code.
ARCHITECTURE = {
    "services": [
        {
            "name": "Ballot Ingest",
            "type": "worker",
            "description": "Loads ballots for each country and stores them.",
            "modules": ["ballots.ingest", "ballots.parse"],
        },
        {
            "name": "Tally Engine",
            "type": "service",
            "description": "Counts votes and publishes results.",
            "modules": ["tally.core"],
        },
    ],
    "tech_stack": {
        "language": "Python",
        "frameworks": ["FastAPI"],
        "databases": ["Postgres"],
    },
    "layers": [{"name": "api", "modules": ["ballots.api"]}],
}

OVERVIEW = (
    "# Overview\n\n"
    "Psephos records national election results and reconciles them against the "
    "official counts published per country.\n\n"
    "It runs as one worker and one API.\n"
)

QUESTIONS = [
    "How are ballots reconciled against the official count?",
    "Where are results stored?",
]


def _profile(**overrides) -> CodebaseProfile:
    kwargs = {
        "project_name": "psephos",
        "architecture": ARCHITECTURE,
        "overview": OVERVIEW,
        "suggestions": QUESTIONS,
    }
    kwargs.update(overrides)
    return CodebaseProfile.build(**kwargs)


@pytest.fixture
def model(monkeypatch):
    """
    Scripts the gate's one model call, and records that it happened.

    `calls` is asserted on as often as the verdict is: a shortcut that quietly stops
    working still returns the right answers, just slower and by a route these cases
    were written to avoid.
    """

    def _install(reply: str | Exception = "{}"):
        state = {"calls": 0, "messages": []}

        async def fake_chat_completion(messages, **kwargs):
            state["calls"] += 1
            state["messages"] = messages
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr("codelith.llm.client.chat_completion", fake_chat_completion)
        return state

    return _install


class TestTheProfile:
    """What the gate compares a question against, read from what analysis wrote."""

    def test_components_stack_and_modules_are_read(self) -> None:
        profile = _profile()

        assert profile.component_lines[0].startswith("Ballot Ingest — Loads ballots")
        assert "FastAPI" in profile.stack
        assert "ballots.ingest" in profile.modules
        # From `layers`, which is the only place a module lands when the architecture
        # pass named no component for it.
        assert "ballots.api" in profile.modules

    def test_the_summary_is_the_first_paragraph_not_the_heading(self) -> None:
        assert _profile().summary.startswith("Psephos records national election results")

    def test_terms_are_this_repository_s_own_words(self) -> None:
        terms = _profile().terms

        assert {"ballots", "tally", "ballot", "ingest", "psephos", "fastapi"} <= terms

    def test_words_every_repository_has_are_not_terms(self) -> None:
        """`service` and `python` match every codebase, so matching on them is the
        same as having no gate at all."""
        terms = _profile().terms

        assert "service" not in terms
        assert "python" not in terms
        assert "core" not in terms

    def test_a_compound_name_is_kept_split_and_whole(self) -> None:
        """Both, because a compound is asked about both ways — and `FastAPI` split
        into `fast` and `api` matched nothing anybody would type."""
        profile = CodebaseProfile.build(
            "x", {"services": [{"name": "FaceTracking", "modules": []}]}
        )

        assert {"face", "tracking", "facetracking"} <= profile.terms
        assert "fastapi" in _profile().terms

    @pytest.mark.parametrize("architecture", [None, "nonsense", 42, {"services": "x"}, {}])
    def test_a_malformed_architecture_column_is_survived(self, architecture) -> None:
        """It is a JSON column holding model output. Every level is checked."""
        profile = CodebaseProfile.build("x", architecture, overview="", suggestions=None)

        assert profile.component_lines == ()
        assert profile.is_thin

    def test_a_thin_profile_says_so_to_the_model(self) -> None:
        """Left as an absence, a model declines everything it does not recognise —
        which is most of a repository it was told nothing about."""
        rendered = CodebaseProfile.build("x").render()

        assert "Analysis recorded little" in rendered

    def test_the_rendered_profile_carries_what_the_repository_is(self) -> None:
        rendered = _profile().render()

        assert "Repository: psephos" in rendered
        assert "Ballot Ingest" in rendered
        assert "Postgres" in rendered
        assert QUESTIONS[0] in rendered


class TestTheShortcut:
    """A question naming something this repository is made of never reaches a model."""

    async def test_a_component_name_settles_it(self, model) -> None:
        state = model()

        verdict = await ScopeGate(_profile()).judge("how does the tally engine work")

        assert verdict.searches_code
        assert verdict.decided_by == "vocabulary"
        assert "tally" in verdict.matched
        assert state["calls"] == 0

    async def test_the_project_s_own_name_settles_it(self, model) -> None:
        state = model()

        verdict = await ScopeGate(_profile()).judge("what is psephos for")

        assert verdict.searches_code and state["calls"] == 0

    async def test_a_path_settles_it(self, model) -> None:
        state = model()

        verdict = await ScopeGate(_profile()).judge("what is in src/entrypoint.py")

        assert verdict.searches_code
        assert verdict.decided_by == "shape"
        assert state["calls"] == 0

    async def test_backticks_settle_it(self, model) -> None:
        state = model()

        verdict = await ScopeGate(_profile()).judge("what does `reconcile_counts` do")

        assert verdict.searches_code and state["calls"] == 0

    async def test_a_capitalised_proper_noun_is_not_a_shortcut(self, model) -> None:
        """`OpenAI` and `New_York` are both code-shaped by the router's patterns, and
        neither is about anybody's repository. Waving them through would let past
        exactly the questions this exists to catch."""
        state = model('{"verdict": "off_topic", "reason": "general", "reply": "no"}')

        verdict = await ScopeGate(_profile()).judge("who founded OpenAI")

        assert state["calls"] == 1
        assert verdict.verdict == OFF_TOPIC

    async def test_a_question_naming_nothing_reaches_the_model(self, model) -> None:
        state = model('{"verdict": "off_topic", "reason": "general knowledge", "reply": "no"}')

        await ScopeGate(_profile()).judge("what is the capital of France")

        assert state["calls"] == 1


class TestVerdicts:
    async def test_off_topic_stops_the_search(self, model) -> None:
        model('{"verdict": "off_topic", "reason": "geography", "reply": "Not from here."}')

        verdict = await ScopeGate(_profile()).judge("what is the capital of France")

        assert not verdict.searches_code
        assert verdict.reply == "Not from here."
        assert verdict.decided_by == "llm"

    async def test_chat_stops_the_search_too(self, model) -> None:
        """A greeting routed into vector search returns the three chunks least
        unlike "hi", and an answer assembled from them."""
        model('{"verdict": "chat", "reason": "a greeting", "reply": "Hello."}')

        verdict = await ScopeGate(_profile()).judge("hey there")

        assert not verdict.searches_code

    async def test_code_runs_the_normal_path(self, model) -> None:
        model('{"verdict": "code", "reason": "about the API", "reply": ""}')

        verdict = await ScopeGate(_profile()).judge("how do I run this locally")

        assert verdict.searches_code
        assert verdict.decided_by == "llm"

    async def test_fences_around_the_json_are_stripped(self, model) -> None:
        model('```json\n{"verdict": "off_topic", "reason": "x", "reply": "y"}\n```')

        assert not (await ScopeGate(_profile()).judge("what is the capital of France")).searches_code

    async def test_a_declined_question_always_has_something_to_say(self, model) -> None:
        """An empty reply would reach the reader as a blank answer — the failure the
        gate was added to prevent, wearing different clothes."""
        model('{"verdict": "off_topic", "reason": "geography", "reply": ""}')

        verdict = await ScopeGate(_profile()).judge("what is the capital of France")

        assert "psephos" in verdict.reply
        assert QUESTIONS[0] in verdict.reply

    async def test_a_greeting_is_not_answered_as_a_refusal(self, model) -> None:
        """A greeting is not a question that was turned down, and telling somebody
        their hello is not something you can answer is a strange way to open."""
        model('{"verdict": "chat", "reason": "a greeting", "reply": ""}')

        verdict = await ScopeGate(_profile()).judge("hey there")

        assert verdict.reply.startswith("I answer questions about psephos")
        assert QUESTIONS[0] in verdict.reply


class TestItFailsOpen:
    """Every uncertain path answers `code`. Refusing a real question about somebody's
    own code is indistinguishable, to them, from the product being broken."""

    async def test_an_unreachable_model_searches_the_code(self, model) -> None:
        model(RuntimeError("connection refused"))

        verdict = await ScopeGate(_profile()).judge("what is the capital of France")

        assert verdict.searches_code
        assert verdict.decided_by == "fallback"

    async def test_an_unparseable_reply_searches_the_code(self, model) -> None:
        model("I think this is probably about geography, honestly")

        assert (await ScopeGate(_profile()).judge("what is the capital of France")).searches_code

    async def test_a_verdict_that_is_not_one_of_the_three_searches_the_code(self, model) -> None:
        model('{"verdict": "unrelated", "reason": "x", "reply": "y"}')

        verdict = await ScopeGate(_profile()).judge("what is the capital of France")

        assert verdict.searches_code
        assert verdict.decided_by == "fallback"

    async def test_a_json_array_searches_the_code(self, model) -> None:
        model('["off_topic"]')

        assert (await ScopeGate(_profile()).judge("what is the capital of France")).searches_code

    async def test_an_empty_question_is_not_judged(self, model) -> None:
        state = model()

        assert (await ScopeGate(_profile()).judge("   ")).verdict == CODE
        assert state["calls"] == 0


class TestTheConversation:
    """The half a question-at-a-time classifier cannot have. "and France?" is about a
    country table or about nothing, and which one was settled two turns ago."""

    async def test_earlier_turns_reach_the_model(self, model) -> None:
        state = model('{"verdict": "code", "reason": "follow-up", "reply": ""}')

        await ScopeGate(_profile()).judge(
            "and France?",
            [
                {"role": "user", "content": "which countries are reconciled nightly"},
                {"role": "assistant", "content": "Seventeen, listed in the schedule."},
            ],
        )

        sent = "\n".join(m["content"] for m in state["messages"])
        assert "which countries are reconciled nightly" in sent
        assert "Seventeen, listed in the schedule." in sent

    async def test_a_first_question_says_so_rather_than_sending_nothing(self, model) -> None:
        state = model('{"verdict": "code", "reason": "x", "reply": ""}')

        await ScopeGate(_profile()).judge("what is the capital of France", [])

        assert "(this is the first question)" in "\n".join(
            m["content"] for m in state["messages"]
        )

    async def test_only_the_last_turns_are_sent(self, model) -> None:
        """What a follow-up refers to is in the last exchange or two. The rest is a
        second subject the gate can only be confused by."""
        state = model('{"verdict": "code", "reason": "x", "reply": ""}')
        history = [{"role": "user", "content": f"turn {i}"} for i in range(10)]

        await ScopeGate(_profile()).judge("and that one?", history)

        sent = "\n".join(m["content"] for m in state["messages"])
        assert "turn 9" in sent
        assert "turn 0" not in sent

    async def test_the_profile_reaches_the_model(self, model) -> None:
        """Without it the gate is a general-purpose topic filter, which cannot tell a
        repository about elections from one about compilers."""
        state = model('{"verdict": "code", "reason": "x", "reply": ""}')

        await ScopeGate(_profile()).judge("what is the capital of France")

        sent = "\n".join(m["content"] for m in state["messages"])
        assert "Psephos records national election results" in sent
        assert "Ballot Ingest" in sent
