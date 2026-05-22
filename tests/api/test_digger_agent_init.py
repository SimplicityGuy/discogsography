"""Tests for the digger agent package init (system prompt loading)."""


def test_system_prompt_loaded() -> None:
    from api.digger_agent import SYSTEM_PROMPT

    assert "Digger" in SYSTEM_PROMPT
    assert "You DO NOT do math" in SYSTEM_PROMPT
    assert "propose_tier_changes" in SYSTEM_PROMPT
