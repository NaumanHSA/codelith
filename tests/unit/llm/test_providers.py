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


class TestTheEndpointFollowsTheProvider:
    """
    Moving a tier to a hosted model has to be the one-word edit the settings comment
    promises. It was not, and the way it failed is the reason these are pinned.

    `MODEL_QUALITY_PROVIDER=openai` with no base URL used to resolve to LM Studio,
    because the base URL defaulted to localhost whatever the provider said. LM Studio
    **answered** — it ignores the model name and replies as whatever it has loaded —
    so every quality call was served by the 1.2b fast model while the settings page
    read `gpt-5.6-luna`, and no call ever failed. An endpoint that returns 200 for the
    wrong model leaves nothing to notice.
    """

    def test_openai_with_no_base_url_goes_to_openai(self, settings_factory) -> None:
        settings_factory(MODEL_QUALITY_PROVIDER=OPENAI, MODEL_QUALITY_BASE_URL="")
        assert providers.spec_for_tier(QUALITY).base_url == "https://api.openai.com/v1"

    def test_local_with_no_base_url_goes_to_lm_studio(self, settings_factory) -> None:
        settings_factory(MODEL_QUALITY_BASE_URL="")
        assert providers.spec_for_tier(QUALITY).base_url == "http://localhost:1234/v1"

    def test_an_explicit_base_url_still_wins(self, settings_factory) -> None:
        """A proxy, a gateway, or another vendor's OpenAI-shaped endpoint."""
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY_BASE_URL="https://gateway.internal/v1",
        )
        assert providers.spec_for_tier(QUALITY).base_url == "https://gateway.internal/v1"

    def test_resolving_one_tier_does_not_move_another(self, settings_factory) -> None:
        """The rule the rest of this file exists for, restated for the new default."""
        settings_factory(MODEL_QUALITY_PROVIDER=OPENAI, MODEL_QUALITY_BASE_URL="")
        assert providers.spec_for_tier(FAST).base_url == "http://localhost:1234/v1"
        assert providers.embedding_spec().base_url == "http://localhost:1234/v1"


class TestTheStartupCheckCatchesTheSilentOne:
    def test_openai_pointed_at_this_machine_is_reported(self, settings_factory) -> None:
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY_BASE_URL="http://localhost:1234/v1",
            OPENAI_API_KEY="sk-test",
        )
        problems = providers.missing_configuration()
        assert any("points at this machine" in p for p in problems)

    @pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0", "host.docker.internal"])
    def test_every_loopback_spelling_counts(self, settings_factory, host: str) -> None:
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY_BASE_URL=f"http://{host}:1234/v1",
            OPENAI_API_KEY="sk-test",
        )
        assert any("points at this machine" in p for p in providers.missing_configuration())

    def test_a_correctly_configured_hosted_tier_is_quiet(self, settings_factory) -> None:
        settings_factory(
            MODEL_QUALITY_PROVIDER=OPENAI,
            MODEL_QUALITY_BASE_URL="",
            OPENAI_API_KEY="sk-test",
        )
        assert providers.missing_configuration() == []
