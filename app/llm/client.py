from functools import lru_cache
from openai import AsyncOpenAI
from app.config import get_settings


@lru_cache
def get_llm_client() -> AsyncOpenAI:
    """Returns a singleton AsyncOpenAI client pointed at LM Studio (or any OpenAI-compatible endpoint)."""
    settings = get_settings()
    return AsyncOpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
    )


async def chat_completion(
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    settings = get_settings()
    client = get_llm_client()

    response = await client.chat.completions.create(
        model=model or settings.LLM_DEFAULT_MODEL,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
        max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


async def create_embedding(text: str, model: str = "text-embedding-ada-002") -> list[float] | None:
    """Create a vector embedding. Returns None if the endpoint doesn't support it."""
    try:
        client = get_llm_client()
        response = await client.embeddings.create(input=text, model=model)
        return response.data[0].embedding
    except Exception:
        return None
