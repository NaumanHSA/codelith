from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


@lru_cache
def get_langchain_llm(task_type: str = "default") -> ChatOpenAI:
    """
    Return a LangChain ChatOpenAI instance pointing at LM Studio.
    Used by ReAct agents (create_react_agent requires a LangChain model).
    task_type controls model selection: 'fast' or anything else → quality model.
    """
    settings = get_settings()
    model = settings.LLM_FAST_MODEL if task_type == "fast" else settings.LLM_QUALITY_MODEL
    return ChatOpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=model,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
    )
