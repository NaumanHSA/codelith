from collections.abc import Sequence
from functools import lru_cache

import structlog
from openai import AsyncOpenAI

from app.config import get_settings
from app.llm.providers import QUALITY, ModelSpec, embedding_spec, spec_for_tier

logger = structlog.get_logger(__name__)


@lru_cache
def _client_for(base_url: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


def get_llm_client(spec: ModelSpec | None = None) -> AsyncOpenAI:
    """
    The client for one endpoint.

    Cached per (base URL, key) rather than globally: the quality and fast tiers may
    now sit on different providers, so "the" client no longer exists. Each distinct
    endpoint gets one long-lived client, which is what keeps its connection pool warm.
    """
    spec = spec or spec_for_tier(QUALITY)
    return _client_for(spec.base_url, spec.api_key)


async def chat_completion(
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool | None = None,
    spec: ModelSpec | None = None,
) -> str:
    """
    Run a chat completion and return the full text.

    Streams by default. Not for latency — for *interruptibility*: a non-streamed call
    is a single opaque await, so cancelling a job left LM Studio generating to the end
    while the UI claimed the job had stopped. Streaming lets us check the cancellation
    token between chunks and abandon the request mid-generation.
    """
    settings = get_settings()
    # `spec` says which endpoint; `model` overrides only the name on it. Callers that
    # pass neither get the quality tier, which is the safe default for an unclassified
    # call — it degrades in cost rather than in output.
    spec = spec or spec_for_tier(QUALITY)
    client = get_llm_client(spec)
    use_stream = settings.LLM_STREAMING if stream is None else stream

    params: dict = {
        "model": model or spec.model,
        "messages": messages,
    }
    if spec.is_local:
        # `LLM_MAX_TOKENS` is a local concern. A served model has no idea what budget
        # it is allowed, and without a ceiling one that loops in its own reasoning
        # generates until something times out. Hosted models stop when they are done
        # and bill for it, so a ceiling there buys nothing and truncates good answers.
        params["max_tokens"] = max_tokens or settings.LLM_MAX_TOKENS
        params["temperature"] = (
            temperature if temperature is not None else settings.LLM_TEMPERATURE
        )
    elif not spec.is_reasoning_model:
        # Ordinary hosted models still take a temperature, and 0.2 is what keeps the
        # JSON-returning stages stable. The reasoning families reject anything but
        # their default, so they are sent nothing at all.
        params["temperature"] = (
            temperature if temperature is not None else settings.LLM_TEMPERATURE
        )

    if not use_stream:
        response = await client.chat.completions.create(**params)  # type: ignore[arg-type]
        return response.choices[0].message.content or ""

    from app.core.cancellation import check_cancelled

    chunks: list[str] = []
    # Reasoning models stream their thinking on a separate delta field, and it is not
    # part of the answer. It is counted anyway, because "the model returned nothing"
    # and "the model thought until it ran out of budget and then returned nothing" are
    # different failures with different fixes, and the second is invisible without it.
    reasoning_chars = 0
    stream_obj = await client.chat.completions.create(**params, stream=True)  # type: ignore[arg-type]
    try:
        async for event in stream_obj:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            if delta and delta.content:
                chunks.append(delta.content)
            if delta and (thinking := getattr(delta, "reasoning_content", None)):
                reasoning_chars += len(thinking)
            # Cheap: the token caches its answer and only hits Redis once a second.
            await check_cancelled()
    finally:
        # Closing the stream aborts the underlying HTTP request, which is what
        # actually stops the model generating.
        await stream_obj.close()

    body = "".join(chunks)
    if not body.strip() and reasoning_chars:
        # The caller raises EmptyCompletion and retries three times with backoff, all
        # inside one traced span — so without this line the whole thing reads as a
        # single very slow call. Measured on job 5: a 221s planner "call" was two
        # reasoning loops that never reached an answer.
        logger.warning(
            "llm_thought_but_did_not_answer",
            model=params["model"],
            reasoning_chars=reasoning_chars,
            max_tokens=params["max_tokens"],
            hint="raise LLM_MAX_TOKENS, or simplify the prompt it is looping on",
        )
    return body


async def create_embedding(text: str, model: str | None = None) -> list[float] | None:
    """Create a vector embedding. Returns None if the endpoint doesn't support it."""
    try:
        # Its own endpoint: moving the writing model to a hosted provider must not
        # move the embedder, whose output size is baked into the database.
        spec = embedding_spec()
        client = get_llm_client(spec)
        response = await client.embeddings.create(
            input=text,
            model=model or spec.model,
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
    spec = embedding_spec()
    client = get_llm_client(spec)
    model = model or spec.model
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
