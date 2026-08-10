from __future__ import annotations

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str):
            total += len(_ENCODING.encode(content))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += len(_ENCODING.encode(part["text"]))
    return total


def count_text_tokens(text: str) -> int:
    """Token count for a bare string, using the same encoding as `count_tokens`."""
    return len(_ENCODING.encode(text or ""))


def count_tokens_lc(messages: list) -> int:
    """count_tokens adapter for LangChain message objects (have a .content attr)."""
    adapted = []
    for m in messages:
        content = getattr(m, "content", "")
        adapted.append({"content": content if isinstance(content, (str, list)) else str(content)})
    return count_tokens(adapted)


def split_for_compaction(messages: list, keep_last: int) -> tuple[list, list]:
    """
    Split a LangChain message history into (older, recent) for compaction.

    `recent` is guaranteed never to begin with an orphan ToolMessage — a
    ToolMessage must stay attached to the AIMessage(tool_calls) that produced it,
    otherwise the chat API rejects the request. The cut index is walked forward
    past any leading ToolMessage so the orphaned tool results land in `older`
    (which is summarised to plain text anyway).
    """
    if len(messages) <= keep_last + 1:
        return [], messages
    cut = len(messages) - keep_last
    while cut < len(messages) and type(messages[cut]).__name__ == "ToolMessage":
        cut += 1
    return messages[:cut], messages[cut:]


def trim_to_limit(messages: list[dict], max_tokens: int) -> list[dict]:
    """
    Trim message list to fit within max_tokens.

    Strategy:
    - Always keep messages[0] (system prompt).
    - Drop the oldest user+assistant pairs from the middle until under limit.
    - If still over after dropping, truncate the last user message content.
    """
    if not messages or count_tokens(messages) <= max_tokens:
        return messages

    # Separate system message from the rest
    system = [messages[0]] if messages[0].get("role") == "system" else []
    rest = messages[len(system):]

    # Drop pairs from the front of rest until we're under the limit
    while len(rest) > 1 and count_tokens(system + rest) > max_tokens:
        rest = rest[2:]  # drop oldest user+assistant pair

    # Last resort: truncate last user message
    if rest and count_tokens(system + rest) > max_tokens:
        last = dict(rest[-1])
        content = last.get("content", "")
        if isinstance(content, str):
            # Binary-search the right character count
            chars = len(content)
            while chars > 100 and count_tokens(system + rest[:-1] + [{"role": last["role"], "content": content[:chars]}]) > max_tokens:
                chars = chars * 3 // 4
            last["content"] = content[:chars] + "\n...[trimmed]"
        rest = rest[:-1] + [last]

    return system + rest


def compact_react_messages(messages: list[dict], keep_last_n: int = 6) -> list[dict]:
    """
    Compact a ReAct agent message history that has grown too long.

    Keeps:
    - messages[0] (system)
    - The last `keep_last_n` messages (most recent context)
    - Inserts a synthetic "memory summary" assistant message before the kept tail
      that summarises tool call results observed so far.
    """
    if len(messages) <= keep_last_n + 1:
        return messages

    system = [messages[0]] if messages[0].get("role") == "system" else []
    rest = messages[len(system):]

    if len(rest) <= keep_last_n:
        return messages

    dropped = rest[:-keep_last_n]
    kept = rest[-keep_last_n:]

    # Summarise key observations from dropped messages
    observations = []
    for m in dropped:
        role = m.get("role", "")
        content = m.get("content") or ""
        if role == "tool" and content:
            observations.append(f"- Tool result: {str(content)[:200]}")
        elif role == "assistant" and content and len(content) > 20:
            observations.append(f"- Agent note: {str(content)[:200]}")

    summary_content = (
        "[Previous context compacted]\n"
        + ("\n".join(observations[:10]) if observations else "No key observations.")
    )
    summary_msg = {"role": "assistant", "content": summary_content}

    return system + [summary_msg] + kept
