"""Unit tests for the perftest harness pure pieces (no live API or DB).

Covers the digger additions: JWT minting parity, path-param interpolation, and
parsing of `digger_scenarios` into the test plan with auth + body + path_params.
"""

from __future__ import annotations

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
