"""Structural checks for the priority-recompute trigger DDL.

The trigger's runtime behavior (recompute max tier across all users wanting a
release on INSERT/UPDATE/DELETE) needs a live Postgres and is exercised by the
M1 e2e smoke (Task 28). These unit tests assert the DDL is present and encodes
the must > nice > eventually precedence — no DB required.
"""

from digger_schema import DIGGER_SCHEMA_SQL


def test_trigger_function_and_trigger_present() -> None:
    sql = DIGGER_SCHEMA_SQL
    assert "FUNCTION digger.recompute_priority_for_release" in sql
    assert "FUNCTION digger.uwp_after_change" in sql
    # CREATE OR REPLACE TRIGGER avoids the drop-then-create gap on every schema-init run
    assert "CREATE OR REPLACE TRIGGER trg_uwp_recompute" in sql
    assert "AFTER INSERT OR UPDATE OR DELETE ON digger.user_wantlist_priorities" in sql


def test_trigger_encodes_tier_precedence() -> None:
    sql = DIGGER_SCHEMA_SQL
    # must wins over nice wins over eventually in the CASE ladder
    must_at = sql.find("bool_or(tier = 'must')")
    nice_at = sql.find("bool_or(tier = 'nice')")
    assert must_at != -1 and nice_at != -1
    assert must_at < nice_at, "must must be evaluated before nice in the precedence ladder"


def test_recompute_resets_to_eventually_when_no_wanters() -> None:
    sql = DIGGER_SCHEMA_SQL
    # When the last user removes a release, max_tier IS NULL and the function must
    # deprioritize the release to 'eventually' rather than leaving a stale tier.
    assert "SET priority_tier = 'eventually'" in sql
    assert "priority_tier IS DISTINCT FROM 'eventually'::digger.priority_tier" in sql
