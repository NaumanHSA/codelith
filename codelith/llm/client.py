from collections.abc import AsyncIterator, Sequence
from functools import lru_cache

import structlog
from openai import AsyncOpenAI

from codelith.config import get_settings
from codelith.llm.providers import QUALITY, ModelSpec, embedding_spec, spec_for_tier

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


def _completion_params(
    messages: list[dict],
    spec: ModelSpec,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
) -> dict:
    """
    The request body for one endpoint.

    Shared by `chat_completion` and `stream_completion` rather than written twice,
    because the differences between tiers are subtle and a second copy is a second
    place for them to drift: `max_tokens` is a local concern, and the reasoning
    families reject a temperature outright.
    """
    settings = get_settings()
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
    return params


async def stream_completion(
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    spec: ModelSpec | None = None,
) -> AsyncIterator[str]:
    """
    Content deltas as the model produces them.

    `chat_completion` already streams — it has to, so a cancelled job stops the model
    rather than draining it — but it accumulates the chunks and returns one string.
    A reader watching an answer appear needs them as they arrive: a grounded answer
    takes five to twenty seconds, and a spinner for that long reads as broken.

    Two things it deliberately does not yield:

    * **Reasoning deltas.** The reasoning families stream their thinking on a separate
      field. It is not the answer, and putting it on screen would show a reader the
      model's rough working as though it were the reply.
    * **Anything after cancellation.** The token is checked between chunks and the
      stream closed, which aborts the underlying HTTP request — that is what actually
      stops the model generating, rather than just stopping us listening.
    """
    from codelith.core.cancellation import check_cancelled

    spec = spec or spec_for_tier(QUALITY)
    client = get_llm_client(spec)
    params = _completion_params(messages, spec, model, temperature, max_tokens)

    reasoning_chars = 0
    answered = False
    stream_obj = await client.chat.completions.create(**params, stream=True)  # type: ignore[arg-type]
    try:
        async for event in stream_obj:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            if delta and delta.content:
                answered = True
                yield delta.content
            if delta and (thinking := getattr(delta, "reasoning_content", None)):
                reasoning_chars += len(thinking)
            await check_cancelled()
    finally:
        await stream_obj.close()

    if not answered and reasoning_chars:
        # Same failure `chat_completion` logs: "returned nothing" and "thought until
        # it ran out of budget and then returned nothing" need different fixes, and
        # the second is invisible without this.
        logger.warning(
            "llm_thought_but_did_not_answer",
            model=params["model"],
            reasoning_chars=reasoning_chars,
            streaming=True,
        )


class ToolsUnsupported(RuntimeError):
    """This endpoint will not take tool definitions. Callers fall back rather than fail."""


async def stream_tool_completion(
    messages: list[dict],
    tools: list[dict],
    spec: ModelSpec | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[dict]:
    """
    One turn that either answers or asks for a tool — streamed either way.

    Yields `{"delta": str}` as content arrives and finally `{"tool_calls": [...]}`,
    which is empty when the model chose to answer.

    **Streamed because the common case is the answer.** The first version of this
    was a plain non-streaming call, on the reasoning that a turn deciding *what to
    look at* has nothing worth watching. Measured, that was expensive in exactly the
    wrong place: "what endpoints does it expose" went from 18s to 45s and made *no*
    tool calls at all. Every question paid a full round-trip for a decision that was
    almost always "no". Streaming it means a turn that does not call a tool has
    already delivered the answer, and the escalation check costs nothing.

    Tool-call arguments arrive as fragments across many frames and are reassembled by
    index — a single call's JSON is routinely split mid-token.

    Raises `ToolsUnsupported` where the endpoint refuses tool definitions, which is
    the common case for small local models. A caller that cannot loop should answer
    from what it already has rather than fail.
    """
    from codelith.core.cancellation import check_cancelled

    spec = spec or spec_for_tier(QUALITY)
    client = get_llm_client(spec)
    params = _completion_params(messages, spec, None, None, max_tokens)

    try:
        stream_obj = await client.chat.completions.create(  # type: ignore[arg-type]
            **params, tools=tools, tool_choice="auto", stream=True
        )
    except Exception as exc:
        text = str(exc).lower()
        if any(hint in text for hint in ("tool", "function")) and any(
            hint in text for hint in ("support", "unrecognized", "unknown", "invalid")
        ):
            raise ToolsUnsupported(str(exc)[:200]) from exc
        raise

    # index → {id, name, arguments}. Fragments accumulate here until the turn ends.
    pending: dict[int, dict] = {}
    spoke = False
    reasoning_chars = 0
    finish_reason: str | None = None

    try:
        async for event in stream_obj:
            if not event.choices:
                continue
            if reason := event.choices[0].finish_reason:
                finish_reason = reason
            delta = event.choices[0].delta
            if delta is None:
                continue

            if delta.content:
                spoke = True
                yield {"delta": delta.content}

            if thinking := getattr(delta, "reasoning_content", None):
                # Not the answer, and not shown. Counted so that a turn which thought
                # and then said nothing is distinguishable from one that returned
                # nothing at all — different causes, different fixes.
                reasoning_chars += len(thinking)

            for call in getattr(delta, "tool_calls", None) or []:
                slot = pending.setdefault(
                    call.index, {"id": "", "name": "", "arguments": ""}
                )
                if call.id:
                    slot["id"] = call.id
                if call.function and call.function.name:
                    slot["name"] = call.function.name
                if call.function and call.function.arguments:
                    slot["arguments"] += call.function.arguments

            await check_cancelled()
    finally:
        await stream_obj.close()

    calls = [pending[index] for index in sorted(pending) if pending[index]["name"]]

    if not spoke and not calls:
        # A silent turn. Without this it is invisible: the caller sees an empty
        # answer and has no way to tell whether the model thought itself into a
        # corner, was cut off mid-sentence, or the endpoint returned nothing at all.
        logger.warning(
            "tool_turn_said_nothing",
            model=spec.model,
            finish_reason=finish_reason,
            reasoning_chars=reasoning_chars,
        )

    yield {"tool_calls": calls}


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

    params = _completion_params(messages, spec, model, temperature, max_tokens)

    if not use_stream:
        response = await client.chat.completions.create(**params)  # type: ignore[arg-type]
        return response.choices[0].message.content or ""

    from codelith.core.cancellation import check_cancelled

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
