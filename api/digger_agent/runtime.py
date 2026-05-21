"""Agent loop with tool dispatch, prompt caching, and an iteration cap.

Yields typed events for the SSE layer to forward:
- {"type": "text", "delta": str}
- {"type": "tool_call", "id": str, "name": str, "input": dict}
- {"type": "tool_result", "id": str, "name": str, "output": dict}
- {"type": "bundle_card", "bundle": dict}
- {"type": "proposal_card", "proposal": dict}
- {"type": "done", "usage": dict, "messages_after": list}

The system prompt + tool definitions are sent with a ``cache_control: ephemeral``
breakpoint so the stable tools->system prefix is cached across turns.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast

from api.digger_agent import SYSTEM_PROMPT
from api.digger_agent.tools.dispatch import dispatch_tool
from api.digger_agent.tools.schemas import TOOL_DEFINITIONS


if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator
    from typing import Any

    import anthropic

    from api.digger_agent.tools.dispatch import ToolContext


log = logging.getLogger(__name__)

_MAX_TOKENS = 4096

# Model aliases -> exact API model IDs (no date suffixes; see claude-api skill).
_MODEL_IDS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}
_DEFAULT_MODEL = _MODEL_IDS["sonnet"]


def _cache_blocks() -> list[dict[str, Any]]:
    """System prompt as a single cached text block (caches the tools->system prefix)."""
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


async def run_agent_turn(
    *,
    client: anthropic.AsyncAnthropic,
    model: str,
    ctx: ToolContext,
    messages: list[dict[str, Any]],
    max_iterations: int = 8,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one user turn to completion, streaming typed events as it goes."""
    model_id = _MODEL_IDS.get(model, _DEFAULT_MODEL)
    current_messages = list(messages)
    total_usage = {"input": 0, "output": 0, "cache_read": 0}

    for _iteration in range(max_iterations):
        async with client.messages.stream(
            model=model_id,
            max_tokens=_MAX_TOKENS,
            # Cast: payloads are plain dicts shaped to the API's TextBlockParam /
            # ToolParam / MessageParam TypedDicts; the API validates the structure.
            system=cast("Any", _cache_blocks()),
            tools=cast("Any", TOOL_DEFINITIONS),
            messages=cast("Any", current_messages),
        ) as stream:
            async for event in stream:
                if getattr(event, "type", None) == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta is not None and getattr(delta, "type", None) == "text_delta":
                        yield {"type": "text", "delta": delta.text}
            final = await stream.get_final_message()

        usage = getattr(final, "usage", None)
        if usage is not None:
            total_usage["input"] += getattr(usage, "input_tokens", 0) or 0
            total_usage["output"] += getattr(usage, "output_tokens", 0) or 0
            total_usage["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0

        assistant_blocks: list[dict[str, Any]] = []
        for block in final.content:
            if block.type == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_blocks.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        current_messages.append({"role": "assistant", "content": assistant_blocks})

        if final.stop_reason != "tool_use":
            break

        tool_results: list[dict[str, Any]] = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool_call", "id": block.id, "name": block.name, "input": block.input}
            result = await dispatch_tool(block.name, block.input or {}, ctx)
            yield {"type": "tool_result", "id": block.id, "name": block.name, "output": result}

            if block.name == "compute_bundles" and "bundles" in result:
                for bundle in result["bundles"]:
                    yield {"type": "bundle_card", "bundle": bundle}
            if block.name == "propose_tier_changes" and "proposal_id" in result:
                yield {"type": "proposal_card", "proposal": result}

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                    "is_error": "error" in result,
                }
            )
        current_messages.append({"role": "user", "content": tool_results})

    yield {"type": "done", "usage": total_usage, "messages_after": current_messages}
