"""Unit tests for the perftest harness pure pieces (no live API or DB).

Covers the digger additions: JWT minting parity, path-param interpolation, and
parsing of `digger_scenarios` into the test plan with auth + body + path_params.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api.auth import decode_token
from tests.perftest import run_perftest as rp


SECRET = "unit-test-secret"


def test_mint_perftest_jwt_decodes_with_secret_and_sub() -> None:
    """The minted token verifies under the secret and carries the perftest sub/email."""
    token = rp.mint_perftest_jwt(secret=SECRET)
    payload = decode_token(token, SECRET)
    assert payload["sub"] == rp.PERFTEST_USER_ID
    assert payload["email"] == rp.PERFTEST_USER_EMAIL
    # Token shape mirrors tests/api/conftest.make_test_jwt: only sub/email/exp.
    assert set(payload) == {"sub", "email", "exp"}


def test_mint_perftest_jwt_rejected_under_wrong_secret() -> None:
    """A token minted under one secret fails verification under another."""
    token = rp.mint_perftest_jwt(secret=SECRET)
    try:
        decode_token(token, "a-different-secret")
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected signature verification to fail")


def test_jwt_sub_matches_seed_user_id() -> None:
    """The minted sub must equal the UUID the seeder uses (auth -> seeded rows)."""
    payload = decode_token(rp.mint_perftest_jwt(secret=SECRET), SECRET)
    assert payload["sub"] == rp.PERFTEST_USER_ID == "00000000-0000-0000-0000-0000000d1996"


def test_perftest_report_id_is_a_distinct_valid_uuid() -> None:
    """The seeded report UUID (used by the reports get/read scenarios) is valid and distinct.

    The reports-by-id and mark-read perftest scenarios target this fixed UUID, so the
    seeder must insert a digger.reports row carrying it. It must not collide with the
    perftest user UUID.
    """
    import uuid

    parsed = uuid.UUID(rp.PERFTEST_REPORT_ID)
    assert str(parsed) == rp.PERFTEST_REPORT_ID
    assert rp.PERFTEST_REPORT_ID != rp.PERFTEST_USER_ID


def test_interpolate_path_fills_release_id() -> None:
    """Path-param interpolation fills {release_id} from path_params."""
    out = rp.interpolate_path("/api/digger/wantlist/{release_id}/priority", {"release_id": 12345})
    assert out == "/api/digger/wantlist/12345/priority"


def test_interpolate_path_noop_without_params() -> None:
    """Paths without placeholders (and no path_params) pass through unchanged."""
    assert rp.interpolate_path("/api/digger/settings", None) == "/api/digger/settings"
    assert rp.interpolate_path("/api/digger/settings", {}) == "/api/digger/settings"


def _digger_config() -> dict[str, Any]:
    return {
        "api_base_url": "http://api:8004",
        "digger_scenarios": [
            {"name": "digger_settings_get", "method": "GET", "path": "/api/digger/settings", "auth": True},
            {
                "name": "digger_wantlist_priority_put",
                "method": "PUT",
                "path": "/api/digger/wantlist/{release_id}/priority",
                "path_params": {"release_id": 12345},
                "body": {"tier": "nice"},
                "auth": True,
            },
            {
                "name": "digger_wantlist_bulk_tier_post",
                "method": "POST",
                "path": "/api/digger/wantlist/bulk-tier",
                "body": {"release_ids": [12345], "tier": "nice"},
                "auth": True,
            },
        ],
    }


def test_build_test_plan_parses_digger_scenarios() -> None:
    """digger_scenarios become plan entries with auth, interpolated paths, and bodies."""
    plan = rp.build_test_plan(_digger_config(), artist_ids={}, label_ids={})
    by_name = {t["name"]: t for t in plan}

    get_t = by_name["digger_settings_get"]
    assert get_t["method"] == "GET"
    assert get_t["auth"] is True
    assert get_t["url"] == "http://api:8004/api/digger/settings"

    put_t = by_name["digger_wantlist_priority_put"]
    assert put_t["method"] == "PUT"
    assert put_t["auth"] is True
    assert put_t["url"] == "http://api:8004/api/digger/wantlist/12345/priority"
    assert put_t["json_body"] == {"tier": "nice"}

    post_t = by_name["digger_wantlist_bulk_tier_post"]
    assert post_t["method"] == "POST"
    assert post_t["auth"] is True
    assert post_t["json_body"] == {"release_ids": [12345], "tier": "nice"}


def test_build_test_plan_without_digger_scenarios_is_empty_when_no_entities() -> None:
    """No digger_scenarios and no entities -> only the static endpoints are present."""
    plan = rp.build_test_plan({"api_base_url": "http://api:8004"}, artist_ids={}, label_ids={})
    names = {t["name"] for t in plan}
    assert not any(n.startswith("digger_") for n in names)


def _digger_m2_config() -> dict[str, Any]:
    """A config exercising the M2 reports + recommend scenarios."""
    return {
        "api_base_url": "http://api:8004",
        "digger_scenarios": [
            {"name": "digger_reports_list", "method": "GET", "path": "/api/digger/reports", "auth": True},
            {
                "name": "digger_reports_get",
                "method": "GET",
                "path": "/api/digger/reports/{report_id}",
                "path_params": {"report_id": rp.PERFTEST_REPORT_ID},
                "auth": True,
            },
            {
                "name": "digger_reports_read",
                "method": "POST",
                "path": "/api/digger/reports/{report_id}/read",
                "path_params": {"report_id": rp.PERFTEST_REPORT_ID},
                "auth": True,
            },
            {
                "name": "digger_recommend",
                "method": "POST",
                "path": "/api/digger/recommend",
                "body": {"deadline_seconds": 5},
                "auth": True,
            },
        ],
    }


def test_build_test_plan_parses_reports_get_by_id() -> None:
    """The reports-by-id GET interpolates {report_id} and carries no body."""
    plan = rp.build_test_plan(_digger_m2_config(), artist_ids={}, label_ids={})
    get_t = {t["name"]: t for t in plan}["digger_reports_get"]
    assert get_t["method"] == "GET"
    assert get_t["auth"] is True
    assert get_t["url"] == f"http://api:8004/api/digger/reports/{rp.PERFTEST_REPORT_ID}"
    assert "json_body" not in get_t


def test_build_test_plan_parses_report_read_post_path_param_no_body() -> None:
    """The mark-read POST interpolates {report_id} and sends no body (json_body is None)."""
    plan = rp.build_test_plan(_digger_m2_config(), artist_ids={}, label_ids={})
    read_t = {t["name"]: t for t in plan}["digger_reports_read"]
    assert read_t["method"] == "POST"
    assert read_t["auth"] is True
    assert read_t["url"] == f"http://api:8004/api/digger/reports/{rp.PERFTEST_REPORT_ID}/read"
    assert read_t["json_body"] is None


def test_build_test_plan_parses_recommend_post_with_body() -> None:
    """The recommend POST (SSE) carries its JSON body and is authenticated."""
    plan = rp.build_test_plan(_digger_m2_config(), artist_ids={}, label_ids={})
    rec_t = {t["name"]: t for t in plan}["digger_recommend"]
    assert rec_t["method"] == "POST"
    assert rec_t["auth"] is True
    assert rec_t["url"] == "http://api:8004/api/digger/recommend"
    assert rec_t["json_body"] == {"deadline_seconds": 5}


def test_real_config_yaml_includes_m2_digger_scenarios() -> None:
    """The shipped config.yaml wires the M2 reports + recommend endpoints end-to-end.

    Guards against config<->runner drift: the new scenarios must parse through the
    real load path and the reports get/read scenarios must target the seeded report
    UUID so the --seed step and the path params stay in sync.
    """
    config_path = Path(__file__).parent / "config.yaml"
    config = rp.load_config(str(config_path))
    plan = rp.build_test_plan(config, artist_ids={}, label_ids={})
    by_name = {t["name"]: t for t in plan}

    for name in ("digger_reports_list", "digger_reports_get", "digger_reports_read", "digger_recommend"):
        assert name in by_name, f"{name} missing from the shipped config plan"

    assert by_name["digger_reports_get"]["url"].endswith(f"/api/digger/reports/{rp.PERFTEST_REPORT_ID}")
    assert by_name["digger_reports_read"]["url"].endswith(f"/api/digger/reports/{rp.PERFTEST_REPORT_ID}/read")


def test_real_config_yaml_includes_m3_digger_scenarios() -> None:
    """The shipped config.yaml wires the M3 agent + proposals endpoints.

    Guards against config<->runner drift for the agent chat turn, the agent
    session list, and the proposals list — all authenticated, and the chat turn
    carrying a user_message body.
    """
    config_path = Path(__file__).parent / "config.yaml"
    config = rp.load_config(str(config_path))
    plan = rp.build_test_plan(config, artist_ids={}, label_ids={})
    by_name = {t["name"]: t for t in plan}

    for name in ("digger_agent_sessions", "digger_proposals_list", "digger_agent_message"):
        assert name in by_name, f"{name} missing from the shipped config plan"
        assert by_name[name]["auth"] is True

    msg = by_name["digger_agent_message"]
    assert msg["method"] == "POST"
    assert msg["url"].endswith("/api/digger/agent/message")
    assert msg["json_body"] == {"user_message": "summarize my wantlist"}
    assert by_name["digger_recommend"]["json_body"] == {"deadline_seconds": 5}
