from collections.abc import Sequence
from functools import lru_cache

import structlog
from openai import AsyncOpenAI

from app.config import get_settings

logger = structlog.get_logger(__name__)


@lru_cache
def get_llm_client() -> AsyncOpenAI:
    """Singleton AsyncOpenAI client pointed at LM Studio (or any OpenAI-compatible endpoint)."""
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


async def create_embedding(text: str, model: str | None = None) -> list[float] | None:
    """Create a vector embedding. Returns None if the endpoint doesn't support it."""
    try:
        settings = get_settings()
        client = get_llm_client()
        response = await client.embeddings.create(
            input=text,
            model=model or settings.EMBEDDING_MODEL,
        )
        return response.data[0].embedding
    except Exception:
        return None


async def create_embeddings(
    texts: Sequence[str],
    model: str | None = None,
    batch_size: int | None = None,
) -> list[list[float] | None]:
    """
    Embed many texts, batching them into as few requests as the endpoint allows.

    Returns a list positionally aligned with `texts`; entries are None where the
    endpoint failed. A failed batch falls back to one-at-a-time so a single bad
    input cannot lose the whole batch.
    """
    if not texts:
        return []

    settings = get_settings()
    client = get_llm_client()
    model = model or settings.EMBEDDING_MODEL
    size = batch_size or settings.EMBEDDING_BATCH_SIZE

    out: list[list[float] | None] = []
    for start in range(0, len(texts), size):
        batch = list(texts[start : start + size])
        try:
            response = await client.embeddings.create(input=batch, model=model)
            # The API may return items out of order; `index` is authoritative.
            ordered = sorted(response.data, key=lambda d: d.index)
            embeddings = [d.embedding for d in ordered]
            if len(embeddings) != len(batch):
                raise ValueError(
                    f"embedding count mismatch: got {len(embeddings)} for {len(batch)} inputs"
                )
            out.extend(embeddings)
        except Exception as exc:
            logger.warning(
                "embedding_batch_failed", error=str(exc), size=len(batch), falling_back=True
            )
            for item in batch:
                out.append(await create_embedding(item, model=model))
    return out
