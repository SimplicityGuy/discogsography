from digger_schema import DIGGER_SCHEMA_SQL


def test_digger_schema_sql_creates_schema_and_enums():
    sql = DIGGER_SCHEMA_SQL
    assert "CREATE SCHEMA IF NOT EXISTS digger" in sql
    for enum_name in (
        "priority_tier",
        "condition",
        "sleeve_condition",
        "region",
        "cadence",
        "model",
        "report_kind",
        "change_flag",
        "confidence",
        "proposal_status",
        "role",
    ):
        assert f"CREATE TYPE digger.{enum_name}" in sql


def test_digger_schema_sql_creates_all_tables():
    sql = DIGGER_SCHEMA_SQL
    for table in (
        "release_scrape_state",
        "sellers",
        "listings",
        "user_wantlist_priorities",
        "user_digger_settings",
        "reports",
        "proposals",
        "agent_sessions",
        "agent_messages",
    ):
        assert f"CREATE TABLE IF NOT EXISTS digger.{table}" in sql
