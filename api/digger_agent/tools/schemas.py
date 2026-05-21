"""JSON schemas for the digger agent tools (Anthropic ``tool_use`` format).

Tier values mirror ``digger.priority_tier`` and bundle names mirror the
``BundleName`` literal in ``common.digger_optimizer.models``. Tools take no
``user_id`` — it is sourced from the JWT at the router boundary via the
``ToolContext`` (see ``dispatch.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from typing import Any


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_wantlist",
        "description": "Return the user's wantlist with current tier and condition-floor assignments. Page size 100.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1, "default": 1},
                "tier_filter": {"type": "string", "enum": ["must", "nice", "eventually"]},
            },
            "required": [],
        },
    },
    {
        "name": "get_user_settings",
        "description": "Return the user's location, currency, scheduled cadence, and preferred model.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_listings_for_release",
        "description": "Return active listings for one release_id, with seller info.",
        "input_schema": {
            "type": "object",
            "properties": {"release_id": {"type": "integer"}},
            "required": ["release_id"],
        },
    },
    {
        "name": "summarize_marketplace_coverage",
        "description": "Aggregate: of the user's must/nice/eventually releases, how many have qualifying listings.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "request_opportunistic_refresh",
        "description": (
            "Trigger fresh scraping of stale listings for the user's wantlist before running the optimizer. "
            "Returns when refresh completes or the deadline elapses."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "deadline_seconds": {"type": "integer", "minimum": 5, "maximum": 60, "default": 30},
            },
            "required": [],
        },
    },
    {
        "name": "compute_bundles",
        "description": (
            "Run the deterministic optimizer and return the named Pareto bundles "
            "(Cheapest, Most Coverage, Best Quality, Fewest Sellers). Use this for ANY cost, coverage, or shipping figure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "budget_cap_cents": {"type": "integer", "minimum": 0},
                "excluded_sellers": {"type": "array", "items": {"type": "integer"}},
            },
            "required": [],
        },
    },
    {
        "name": "explain_bundle",
        "description": "Itemized breakdown of one bundle from a recent compute_bundles result: releases, sellers, per-item prices, shipping.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bundle_name": {
                    "type": "string",
                    "enum": ["cheapest", "most_coverage", "best_quality", "fewest_sellers"],
                },
            },
            "required": ["bundle_name"],
        },
    },
    {
        "name": "save_report",
        "description": "Persist the most recently computed bundles to the user's inbox.",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 120}},
            "required": ["title"],
        },
    },
    {
        "name": "propose_tier_changes",
        "description": "Submit a proposal for tier changes. Pending until the user approves in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": {
                        "type": "object",
                        "properties": {
                            "release_id": {"type": "integer"},
                            "proposed_tier": {"type": "string", "enum": ["must", "nice", "eventually"]},
                            "reason": {"type": "string", "maxLength": 240},
                        },
                        "required": ["release_id", "proposed_tier", "reason"],
                    },
                },
            },
            "required": ["changes"],
        },
    },
]

TOOL_NAMES: set[str] = {t["name"] for t in TOOL_DEFINITIONS}
