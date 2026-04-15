"""NLQ engine — Claude tool-use loop orchestration.

Runs the iterative conversation between the user's query, Claude, and the
tool runner. Handles system prompts, auth-aware tool selection, off-topic
guardrails, entity deduplication, and an optional SSE status callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any

import structlog

from api.nlq.tools import get_action_tool_schemas, get_authenticated_tool_schemas, get_public_tool_schemas


if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Awaitable, Callable

    from api.nlq.actions import Action
    from api.nlq.config import NLQConfig
    from api.nlq.tools import NLQToolRunner

logger = structlog.get_logger(__name__)

# ── System prompt ────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a music knowledge graph assistant for Discogsography. You help users \
explore a graph of artists, labels, releases, genres, and styles from the \
Discogs music database.

Use the provided tools to answer questions. Always ground your answers in \
tool results — never fabricate data. If a tool returns no results, say so honestly.

When mentioning entities, use their exact names as returned by tools so the \
UI can link them. Keep responses concise (2-4 sentences for simple queries, \
up to a short paragraph for complex ones).

Supported entity types: artist, label, genre, style.
Releases are searchable but not directly explorable as graph nodes.

You can ONLY answer questions about music, artists, labels, releases, genres, \
and styles in the Discogsography knowledge graph. If a question is unrelated \
to music or this database, politely decline and suggest a music-related query.

Do NOT answer general knowledge questions, even if music-adjacent (e.g., band \
member biographies, music theory, concert schedules). Your knowledge comes \
exclusively from the tools provided.

When your answer should mutate the UI, invoke the appropriate action tool(s) \
— seed_graph, switch_pane, filter_graph, ui_find_path, highlight_path, \
focus_node, show_credits, open_insight_tile, set_trend_range, or \
suggest_followups — after fetching data with the data tools. Action tools \
record the UI effect; they do not fetch data. Only emit actions that directly \
follow from the user's question."""

_AUTH_ADDENDUM = """

The user is logged in and has a Discogs collection. You can access their \
collection stats, taste fingerprint, blindspots, and gap analysis."""

# ── Off-topic refusal keywords ──────────────────────────────────────────

_REFUSAL_KEYWORDS = ("i can only help", "i can only answer", "i can't help", "i cannot help", "not able to help", "outside my scope")

_OFF_TOPIC_REDIRECT = "I can only answer questions about the Discogsography music database. Try asking about an artist, label, or genre!"


# ── Dataclasses ──────────────────────────────────────────────────────────


@dataclass
class NLQContext:
    """Context passed to the NLQ engine for each query."""

    user_id: str | None = None
    current_entity_id: str | None = None
    current_entity_type: str | None = None


@dataclass
class NLQResult:
    """Result returned by the NLQ engine."""

    summary: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)


# ── Engine ───────────────────────────────────────────────────────────────


class NLQEngine:
    """Orchestrates the Claude tool-use loop for natural language queries.

    The engine builds the Claude API request with the system prompt and
    auth-aware tool list, then loops: send request -> if tool_use, execute
    tools and loop -> if end_turn, return result.
    """

    def __init__(self, config: NLQConfig, client: Any, tool_runner: NLQToolRunner) -> None:
        self._config = config
        self._client = client
        self._tool_runner = tool_runner

    async def run(
        self,
        query: str,
        context: NLQContext,
        on_status: Callable[[str], Awaitable[None]] | None = None,
    ) -> NLQResult:
        """Run the tool-use loop for a user query.

        Args:
            query: The user's natural language question.
            context: Auth and entity context for the query.
            on_status: Optional async callback invoked with status messages
                       (e.g. ``"Running search..."``) for SSE streaming.

        Returns:
            An ``NLQResult`` with the summary, extracted entities, and tools used.
        """
        system_prompt = _SYSTEM_PROMPT
        if context.user_id is not None:
            system_prompt += _AUTH_ADDENDUM

        tools = get_public_tool_schemas()
        tools.extend(get_action_tool_schemas())
        if context.user_id is not None:
            tools.extend(get_authenticated_tool_schemas())

        messages: list[dict[str, Any]] = [{"role": "user", "content": query}]
        tools_used: list[str] = []
        entities: list[dict[str, Any]] = []
        actions: list[Action] = []
        response = None

        for _iteration in range(self._config.max_iterations):
            response = await self._client.messages.create(
                model=self._config.model,
                system=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=1024,
            )

            if response.stop_reason == "end_turn":
                summary = _extract_text(response)
                return self._build_result(summary, entities, tools_used, actions)

            # Execute each tool_use block
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "tool_use":
                    if on_status is not None:
                        await on_status(f"Running {block.name}...")

                    result = await self._tool_runner.execute(
                        block.name,
                        block.input,
                        context.user_id,
                        action_recorder=actions,
                    )
                    tools_used.append(block.name)
                    entities.extend(self._tool_runner.extract_entities(block.name, result))
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        }
                    )

            messages.append({"role": "assistant", "content": response.content})
            if not tool_results:
                # Non-tool stop (e.g., max_tokens) — treat as final response.
                summary = _extract_text(response)
                return self._build_result(summary, entities, tools_used, actions)
            messages.append({"role": "user", "content": tool_results})

        # Max iterations reached — return whatever we have
        logger.warning("⚠️ NLQ engine reached max iterations", max_iterations=self._config.max_iterations)
        summary = _extract_text(response) if response else ""
        return self._build_result(summary, entities, tools_used, actions)

    def _build_result(
        self,
        summary: str,
        entities: list[dict[str, Any]],
        tools_used: list[str],
        actions: list[Action],
    ) -> NLQResult:
        """Build an NLQResult with guardrails and entity deduplication."""
        if not tools_used:
            summary = _apply_off_topic_guardrail(summary)
        deduped = _deduplicate_entities(entities)
        return NLQResult(summary=summary, entities=deduped, tools_used=tools_used, actions=actions)


# ── Helpers ──────────────────────────────────────────────────────────────


def _extract_text(response: Any) -> str:
    """Extract concatenated text from a Claude response."""
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return " ".join(parts) if parts else ""


def _apply_off_topic_guardrail(summary: str) -> str:
    """Replace off-topic responses with a redirect message.

    If the summary contains refusal keywords, it's Claude already declining
    — pass it through. If the summary is empty, return the redirect.
    Otherwise, pass through — a non-empty, non-refusal response without
    tools may be a valid answer from system prompt context.
    """
    if not summary.strip():
        return _OFF_TOPIC_REDIRECT
    lower = summary.lower()
    for keyword in _REFUSAL_KEYWORDS:
        if keyword in lower:
            return summary
    # Non-empty response without refusal keywords — may be a valid on-topic
    # answer from system prompt context. Pass through instead of replacing.
    return summary


def _deduplicate_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate entities by (id, type) tuple, preserving order."""
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for entity in entities:
        key = (entity.get("id", ""), entity.get("type", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(entity)
    return deduped
