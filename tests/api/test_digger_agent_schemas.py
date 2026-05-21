"""Tests for the digger agent tool schemas (Anthropic tool_use format)."""

from api.digger_agent.tools.schemas import TOOL_DEFINITIONS, TOOL_NAMES


def test_all_expected_tools_defined() -> None:
    assert {
        "get_wantlist",
        "get_user_settings",
        "get_listings_for_release",
        "summarize_marketplace_coverage",
        "request_opportunistic_refresh",
        "compute_bundles",
        "explain_bundle",
        "save_report",
        "propose_tier_changes",
    } == TOOL_NAMES


def test_each_definition_has_required_keys() -> None:
    for t in TOOL_DEFINITIONS:
        assert {"name", "description", "input_schema"} <= set(t)
        schema = t["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_definitions_and_names_agree() -> None:
    assert {t["name"] for t in TOOL_DEFINITIONS} == TOOL_NAMES
    assert len(TOOL_DEFINITIONS) == len(TOOL_NAMES)
