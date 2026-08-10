from functools import lru_cache

from langchain_openai import ChatOpenAI

from codelith.config import get_settings
from codelith.llm.providers import FAST, QUALITY, spec_for_tier


@lru_cache
def get_langchain_llm(task_type: str = "default") -> ChatOpenAI:
    """
    A LangChain model for whichever endpoint the tier resolves to.

    `create_react_agent` requires a LangChain model, so this mirrors
    `app/llm/client.py` rather than replacing it. Both read the same specs, so the
    two tiers can sit on different providers here too — a ReAct agent on the fast
    tier keeps talking to the local endpoint when the quality tier moves to OpenAI.
    """
    settings = get_settings()
    spec = spec_for_tier(FAST if task_type == "fast" else QUALITY)
    return ChatOpenAI(
        base_url=spec.base_url,
        api_key=spec.api_key,
        model=spec.model,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
    )
