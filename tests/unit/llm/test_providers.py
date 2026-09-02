"""
Resolving a tier to an endpoint.

The rule that matters: the two tiers choose independently. Half of this file exists to
pin that a hosted quality tier does not drag the fast tier or — worse — the embedder
along with it, because the embedder's output size is written into the database and
moving it silently is a destructive migration away.
"""

from __future__ import annotations

import pytest

from codelith.config import Settings
from codelith.llm import providers
from codelith.llm.providers import FAST, LOCAL, OPENAI, QUALITY


@pytest.fixture
def settings_factory(monkeypatch):
    """Build a Settings from overrides and make every resolver read it."""

    def build(**overrides):
        base = dict(
            MODEL_QUALITY_PROVIDER="local",
            MODEL_QUALITY="qwen/qwen3.5-9b",
            MODEL_QUALITY_BASE_URL="http://localhost:1234/v1",
            MODEL_QUALITY_CONTEXT_WINDOW=21000,
            MODEL_FAST_PROVIDER="local",
            MODEL_FAST="liquid/lfm2.5-1.2b",
            MODEL_FAST_BASE_URL="http://localhost:1234/v1",
            MODEL_FAST_CONTEXT_WINDOW=21000,
            MODEL_EMBEDDING_PROVIDER="local",
            MODEL_EMBEDDING="nomic-embed",
            MODEL_EMBEDDING_BASE_URL="http://localhost:1234/v1",
            OPENAI_API_KEY="sk-test",
        )
        base.update(overrides)
        s = Settings(**base)
        monkeypatch.setattr(providers, "get_settings", lambda: s)
        return s

    return build


class TestTierResolution:
    def test_local_tier_uses_the_local_endpoint(self, settings_factory) -> None:
        settings_factory()
        spec = providers.spec_for_tier(QUALITY)

        assert spec.provider == LOCAL
        assert spec.model == "qwen/qwen3.5-9b"
        assert spec.base_url == "http://localhost:1234/v1"
        assert spec.context_window == 21000
        assert spec.is_local

    def test_openai_tier_uses_the_hosted_endpoint(self, settings_factory) -> None:
        settings_factory(
            MODEL_QUALITY_PROVIDER="openai",
            MODEL_QUALITY="gpt-4o-mini",
            MODEL_QUALITY_BASE_URL="https://api.openai.com/v1",
            MODEL_QUALITY_CONTEXT_WINDOW=128_000,
        )
        spec = providers.spec_for_tier(QUALITY)

        assert spec.provider == OPENAI
        assert spec.model == "gpt-4o-mini"
        assert spec.base_url == "https://api.openai.com/v1"
        assert spec.api_key == "sk-test"
        assert spec.context_window == 128_000

    def test_the_tiers_are_independent(self, settings_factory) -> None:
        """The whole point: cheap local bulk work, hosted writing."""
        settings_factory(MODEL_QUALITY_PROVIDER="openai", MODEL_FAST_PROVIDER="local")

        assert providers.spec_for_tier(QUALITY).provider == OPENAI
        assert providers.spec_for_tier(FAST).provider == LOCAL
        assert providers.spec_for_tier(FAST).model == "liquid/lfm2.5-1.2b"

    def test_a_local_tier_never_carries_the_openai_key(self, settings_factory) -> None:
        """A key configured for a hosted provider has no business reaching localhost."""
        settings_factory(MODEL_QUALITY_PROVIDER="local", OPENAI_API_KEY="sk-secret")

        assert providers.spec_for_tier(QUALITY).api_key == "not-needed"

    def test_an_unknown_tier_falls_back_to_quality(self, settings_factory) -> None:
        settings_factory()

        assert providers.spec_for_tier("nonsense").model == "qwen/qwen3.5-9b"


class TestEmbeddings:
    def test_embeddings_do_not_follow_the_quality_tier(self, settings_factory) -> None:
        """
        The load-bearing one. `VECTOR_DIMENSIONS` is baked into
        `code_chunks.embedding` at migration time, so an embedder that quietly moved
        with the writing model would mean a truncating migration and a full re-ingest.
        """
        settings_factory(MODEL_QUALITY_PROVIDER="openai", MODEL_EMBEDDING_PROVIDER="local")
        spec = providers.embedding_spec()

        assert spec.provider == LOCAL
        assert spec.base_url == "http://localhost:1234/v1"
        assert spec.model == "nomic-embed"

    def test_embeddings_can_be_hosted_on_their_own(self, settings_factory) -> None:
        settings_factory(MODEL_QUALITY_PROVIDER="local", MODEL_EMBEDDING_PROVIDER="openai")

        assert providers.embedding_spec().provider == OPENAI


class TestReasoningModels:
    """
    OpenAI's reasoning families reject `max_tokens` and non-default `temperature`.

    Measured live: `gpt-5-mini` returns 400 "Unsupported parameter: 'max_tokens' is
    not supported with this model. Use 'max_completion_tokens' instead."
    """

    @pytest.mark.parametrize(
        "model", ["gpt-5-mini", "gpt-5", "o3-mini", "o4-mini", "GPT-5-Pro"]
    )
    def test_openai_reasoning_families_are_recognised(self, settings_factory, model) -> None:
        settings_factory(MODEL_QUALITY_PROVIDER="openai", MODEL_QUALITY=model)

        assert providers.spec_for_tier(QUALITY).is_reasoning_model

    @pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-4.1", "gpt-4o"])
    def test_ordinary_openai_models_are_not(self, settings_factory, model) -> None:
        settings_factory(MODEL_QUALITY_PROVIDER="openai", MODEL_QUALITY=model)

        assert not providers.spec_for_tier(QUALITY).is_reasoning_model

    def test_a_local_reasoning_model_keeps_the_legacy_parameters(
        self, settings_factory
    ) -> None:
        """
        LM Studio serves reasoning models too — qwen3.5 is one — but accepts
        `max_tokens`. Treating it like OpenAI would break every local setup.
        """
        settings_factory(MODEL_QUALITY_PROVIDER="local", MODEL_QUALITY="gpt-5-lookalike")

        assert not providers.spec_for_tier(QUALITY).is_reasoning_model


class TestConfigurationChecks:
    def test_openai_without_a_key_is_reported(self, settings_factory) -> None:
        settings_factory(MODEL_QUALITY_PROVIDER="openai", OPENAI_API_KEY="")
        problems = providers.missing_configuration()

        assert any("OPENAI_API_KEY" in p for p in problems)

    def test_a_missing_model_name_is_reported(self, settings_factory) -> None:
        settings_factory(MODEL_FAST="")
        problems = providers.missing_configuration()

        assert any("MODEL_FAST" in p for p in problems)

    def test_a_fully_local_setup_needs_no_key(self, settings_factory) -> None:
        settings_factory(OPENAI_API_KEY="")

        assert providers.missing_configuration() == []


class TestProviderValidation:
    def test_a_typo_fails_at_startup(self) -> None:
        with pytest.raises(ValueError, match="provider must be one of"):
            Settings(MODEL_QUALITY_PROVIDER="opanai")

    @pytest.mark.parametrize("value", ["OpenAI", "LOCAL", " openai "])
    def test_case_and_whitespace_are_forgiven(self, value) -> None:
        assert Settings(MODEL_QUALITY_PROVIDER=value).MODEL_QUALITY_PROVIDER in {"local", "openai"}


class TestRouting:
    def test_task_types_map_to_the_documented_tiers(self, settings_factory) -> None:
        from codelith.llm.router import select_tier

        assert select_tier("write") == QUALITY
        assert select_tier("plan") == QUALITY
        assert select_tier("diagram") == QUALITY
        assert select_tier("summarize") == FAST
        assert select_tier("classify") == FAST
        # Unclassified degrades in cost, not in output.
        assert select_tier("something-new") == QUALITY


class TestTheProviderDecidesWhatIsRead:
    """
    The two providers need genuinely different things, and the provider is dispatched
    on *before* anything else is read.

    They used to share one shape — provider, model, base URL, window — with the
    provider deciding only whether a real key travelled. So `MODEL_QUALITY_PROVIDER=
    openai` on its own resolved to LM Studio, which **answered**: it ignores the model
    name and replies as whatever it has loaded. The quality tier was served by a 1.2b
    model while the settings said `gpt-5.6-luna`, every call returned 200, and nothing
    showed it. These pin the shape that makes that unrepresentable.
    """

    def test_openai_needs_only_a_key_and_a_model(self, settings_factory) -> None:
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY="gpt-5.6-luna",
            OPENAI_API_KEY="sk-test",
        )
        spec = providers.spec_for_tier(QUALITY)

        assert spec.base_url == providers.OPENAI_BASE_URL
        assert spec.model == "gpt-5.6-luna"
        assert spec.api_key == "sk-test"
        assert spec.context_window == providers.OPENAI_CONTEXT_WINDOW

    def test_an_openai_tier_ignores_a_base_url_entirely(self, settings_factory) -> None:
        """
        The one that matters. A leftover `MODEL_QUALITY_BASE_URL` in somebody's `.env`
        — which is exactly how this went wrong — cannot redirect a hosted tier.
        Pointing elsewhere is what the `local` provider is for.
        """
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY_BASE_URL="http://localhost:1234/v1",
            OPENAI_API_KEY="sk-test",
        )
        assert providers.spec_for_tier(QUALITY).base_url == providers.OPENAI_BASE_URL

    def test_an_openai_tier_ignores_a_context_window(self, settings_factory) -> None:
        """Not a number anybody should have to look up to use their own account."""
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY_CONTEXT_WINDOW=4096,
            OPENAI_API_KEY="sk-test",
        )
        assert providers.spec_for_tier(QUALITY).context_window == (
            providers.OPENAI_CONTEXT_WINDOW
        )

    def test_a_compatible_tier_reads_all_three(self, settings_factory) -> None:
        """vLLM, Ollama, a gateway — nothing about these can be assumed."""
        settings_factory(
            MODEL_QUALITY_PROVIDER=LOCAL,
            MODEL_QUALITY="mistral-7b",
            MODEL_QUALITY_BASE_URL="http://10.0.0.4:8000/v1",
            MODEL_QUALITY_CONTEXT_WINDOW=32768,
        )
        spec = providers.spec_for_tier(QUALITY)

        assert (spec.base_url, spec.model, spec.context_window) == (
            "http://10.0.0.4:8000/v1", "mistral-7b", 32768,
        )
        assert spec.api_key != "sk-test", "a real key has no business leaving the box"

    def test_a_compatible_tier_with_no_url_falls_back_to_lm_studio(
        self, settings_factory
    ) -> None:
        settings_factory(MODEL_QUALITY_BASE_URL="")
        assert providers.spec_for_tier(QUALITY).base_url == providers.LOCAL_BASE_URL

    def test_moving_one_tier_to_openai_does_not_move_another(
        self, settings_factory
    ) -> None:
        """
        The rule the rest of this file exists for. The embedder especially: its output
        width is written into every stored vector, so moving it is a re-ingest.
        """
        settings_factory(MODEL_QUALITY_PROVIDER=OPENAI, OPENAI_API_KEY="sk-test")

        assert providers.spec_for_tier(FAST).base_url == "http://localhost:1234/v1"
        assert providers.embedding_spec().base_url == "http://localhost:1234/v1"
        assert providers.embedding_spec().api_key != "sk-test"


class TestTheStartupCheck:
    def test_openai_without_a_key_is_refused(self, settings_factory) -> None:
        settings_factory(MODEL_QUALITY_PROVIDER=OPENAI, OPENAI_API_KEY="")
        problems = providers.missing_configuration()

        assert any("OPENAI_API_KEY is empty" in p for p in problems)
        assert any("MODEL_QUALITY_PROVIDER=local" in p for p in problems), (
            "say what the alternative is, not just what is missing"
        )

    def test_a_compatible_tier_with_no_window_is_refused(self, settings_factory) -> None:
        """Prompts are budgeted against it; zero leaves no room for evidence."""
        settings_factory(MODEL_QUALITY_CONTEXT_WINDOW=0)
        assert any(
            "MODEL_QUALITY_CONTEXT_WINDOW" in p for p in providers.missing_configuration()
        )

    def test_the_embedder_needs_no_window(self, settings_factory) -> None:
        """Nothing trims an embedding request."""
        settings_factory()
        assert not any(
            "MODEL_EMBEDDING_CONTEXT_WINDOW" in p for p in providers.missing_configuration()
        )

    def test_openai_needs_no_url_or_window(self, settings_factory) -> None:
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY_BASE_URL="",
            MODEL_QUALITY_CONTEXT_WINDOW=0,
            OPENAI_API_KEY="sk-test",
        )
        assert providers.missing_configuration() == []
