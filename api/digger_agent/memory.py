"""Conversation memory with a summarization anchor.

When a session's history grows past ``MAX_TURNS`` messages or ``MAX_TOKENS``
(approx), the older head is collapsed into a single "[prior context summary]"
anchor message (summarized by Haiku when an Anthropic client is supplied, or a
truncated text fallback otherwise) and only the recent tail is replayed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from api.queries.digger_agent_queries import list_messages


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any
    import uuid

    import anthropic

    from common import AsyncPostgreSQLPool


log = logging.getLogger(__name__)

MAX_TURNS = 20
MAX_TOKENS = 50_000

# Cheap model for the one-shot history summary (see claude-api skill: no date suffix).
_SUMMARY_MODEL = "claude-haiku-4-5"

ANCHOR_PROMPT = (
    "Summarize the following Digger conversation history in 200 words or fewer, "
    "preserving any user-stated constraints (budget, regions, etc.) and any tier "
    "changes the user approved or rejected. Return only the summary."
)


def _iter_blocks(content: Any) -> list[Any]:
    return content if isinstance(content, list) else [{"text": str(content)}]


def _approx_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        for c in _iter_blocks(m["content"]):
            if isinstance(c, dict) and "text" in c:
                total += len(c["text"]) // 4
    return total


def _dump_for_summary(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        role = m["role"]
        for c in _iter_blocks(m["content"]):
            if isinstance(c, dict) and "text" in c:
                parts.append(f"{role}: {c['text']}")
    return "\n".join(parts)


async def _summarize(client: anthropic.AsyncAnthropic, head: list[dict[str, Any]]) -> str:
    try:
        resp = await client.messages.create(
            model=_SUMMARY_MODEL,
            max_tokens=400,
            system=ANCHOR_PROMPT,
            messages=[{"role": "user", "content": _dump_for_summary(head)}],
        )
        return str(getattr(resp.content[0], "text", "(prior context truncated)"))
    except Exception:
        log.exception("🧠 digger agent history summarization failed; using truncated text")
        return "(prior context truncated)"


async def build_message_history(
    pool: AsyncPostgreSQLPool,
    session_id: uuid.UUID,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Return ``(messages_to_replay, anchor_or_None)`` for a session.

    Under the caps, returns all messages and ``None``. Over a cap, returns the
    recent tail plus a single summary anchor to prepend before it.
    """
    msgs = await list_messages(pool, session_id)
    if len(msgs) <= MAX_TURNS * 2 and _approx_tokens(msgs) <= MAX_TOKENS:
        return msgs, None
    head = msgs[:-MAX_TURNS]
    tail = msgs[-MAX_TURNS:]
    if client is None:
        flat = _dump_for_summary(head)
        summary = flat[:1000]
    else:
        summary = await _summarize(client, head)
    anchor = {"role": "user", "content": [{"type": "text", "text": f"[prior context summary]: {summary}"}]}
    return tail, anchor
