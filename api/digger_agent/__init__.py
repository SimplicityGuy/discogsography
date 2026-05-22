"""LLM agent runtime for the Digger feature.

Exposes the agent system prompt loaded from ``prompts/system.md``. The agent
delegates all numeric work to the deterministic M2 services (the optimizer in
``common.digger_optimizer`` and the refresh/reports helpers in ``api``); see
``api/digger_agent/runtime.py`` for the tool-using loop.
"""

from pathlib import Path


_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"
SYSTEM_PROMPT: str = _PROMPT_PATH.read_text(encoding="utf-8")
