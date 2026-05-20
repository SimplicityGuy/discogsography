"""Digger feature Postgres schema.

Owns all digger.* tables, enums, indices, and triggers. Invoked by
schema-init at container start (idempotent via IF NOT EXISTS).
"""

DIGGER_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS digger;

DO $$ BEGIN
    CREATE TYPE digger.priority_tier   AS ENUM ('must', 'nice', 'eventually');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.condition       AS ENUM ('M','NM','VG+','VG','G+','G','F','P');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.sleeve_condition AS ENUM ('M','NM','VG+','VG','G+','G','F','P','generic','no_cover');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.region          AS ENUM ('us','ca','eu','uk','jp','au','other');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.cadence         AS ENUM ('off','weekly','biweekly','monthly');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.model           AS ENUM ('haiku','sonnet','opus');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.report_kind     AS ENUM ('scheduled','interactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.change_flag     AS ENUM ('significant','none','first_run');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.confidence      AS ENUM ('high','low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.proposal_status AS ENUM ('pending','approved','rejected','expired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE digger.role            AS ENUM ('system','user','assistant','tool');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS digger.sellers (
    seller_id              bigint        PRIMARY KEY,
    username               text          NOT NULL,
    country_code           char(2),
    region                 digger.region NOT NULL DEFAULT 'other',
    feedback_count         int,
    feedback_score         numeric(4,1),
    ships_internationally  bool          NOT NULL DEFAULT false,
    shipping_policy        jsonb,
    last_refreshed_at      timestamptz   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS digger.release_scrape_state (
    release_id             bigint                PRIMARY KEY,
    priority_tier          digger.priority_tier  NOT NULL DEFAULT 'eventually',
    last_scraped_at        timestamptz,
    next_scrape_due_at     timestamptz           NOT NULL DEFAULT now(),
    listings_delta_7d      int                   NOT NULL DEFAULT 0,
    consecutive_failures   int                   NOT NULL DEFAULT 0,
    next_retry_at          timestamptz
);

CREATE INDEX IF NOT EXISTS idx_rss_due_tier
    ON digger.release_scrape_state (priority_tier, next_scrape_due_at);

CREATE TABLE IF NOT EXISTS digger.listings (
    listing_id          bigint                   PRIMARY KEY,
    release_id          bigint                   NOT NULL REFERENCES digger.release_scrape_state(release_id) ON DELETE CASCADE,
    seller_id           bigint                   NOT NULL REFERENCES digger.sellers(seller_id) ON DELETE CASCADE,
    price_value         numeric(10,2)            NOT NULL,
    price_currency      char(3)                  NOT NULL,
    media_condition     digger.condition         NOT NULL,
    sleeve_condition    digger.sleeve_condition  NOT NULL,
    comments            text,
    posted_at           timestamptz,
    first_seen_at       timestamptz              NOT NULL DEFAULT now(),
    last_seen_at        timestamptz              NOT NULL DEFAULT now(),
    removed_at          timestamptz
);

CREATE INDEX IF NOT EXISTS idx_listings_release_active
    ON digger.listings (release_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_listings_seller_active
    ON digger.listings (seller_id) WHERE removed_at IS NULL;

CREATE TABLE IF NOT EXISTS digger.user_wantlist_priorities (
    user_id              uuid                    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    release_id           bigint                  NOT NULL,
    tier                 digger.priority_tier    NOT NULL DEFAULT 'nice',
    min_media_condition  digger.condition        NOT NULL DEFAULT 'VG',
    min_sleeve_condition digger.sleeve_condition NOT NULL DEFAULT 'VG',
    max_price_cents      int,
    updated_at           timestamptz             NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, release_id)
);

CREATE INDEX IF NOT EXISTS idx_uwp_release ON digger.user_wantlist_priorities (release_id);

CREATE TABLE IF NOT EXISTS digger.user_digger_settings (
    user_id                       uuid             PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled                       bool             NOT NULL DEFAULT false,
    country_code                  char(2),
    currency                      char(3)          NOT NULL DEFAULT 'USD',
    scheduled_cadence             digger.cadence   NOT NULL DEFAULT 'off',
    next_scheduled_run_at         timestamptz,
    preferred_model               digger.model     NOT NULL DEFAULT 'sonnet',
    daily_token_cap_interactive   int              NOT NULL DEFAULT 200000,
    daily_token_cap_scheduled     int              NOT NULL DEFAULT 100000
);

CREATE TABLE IF NOT EXISTS digger.reports (
    report_id            uuid                     PRIMARY KEY,
    user_id              uuid                     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind                 digger.report_kind       NOT NULL,
    generated_at         timestamptz              NOT NULL DEFAULT now(),
    read_at              timestamptz,
    title                text                     NOT NULL,
    summary              jsonb                    NOT NULL,
    bundles              jsonb                    NOT NULL,
    watching             jsonb                    NOT NULL DEFAULT '[]'::jsonb,
    change_flag          digger.change_flag       NOT NULL,
    shipping_confidence  digger.confidence        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_user_time
    ON digger.reports (user_id, generated_at DESC);

CREATE TABLE IF NOT EXISTS digger.proposals (
    proposal_id  uuid                     PRIMARY KEY,
    user_id      uuid                     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id   uuid,
    created_at   timestamptz              NOT NULL DEFAULT now(),
    status       digger.proposal_status   NOT NULL DEFAULT 'pending',
    payload      jsonb                    NOT NULL,
    expires_at   timestamptz              NOT NULL
);

CREATE TABLE IF NOT EXISTS digger.agent_sessions (
    session_id              uuid           PRIMARY KEY,
    user_id                 uuid           NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at              timestamptz    NOT NULL DEFAULT now(),
    last_active_at          timestamptz    NOT NULL DEFAULT now(),
    model                   digger.model   NOT NULL,
    total_input_tokens      int            NOT NULL DEFAULT 0,
    total_output_tokens     int            NOT NULL DEFAULT 0,
    total_cache_read_tokens int            NOT NULL DEFAULT 0,
    total_cost_usd          numeric(10,4)  NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS digger.agent_messages (
    message_id    uuid          PRIMARY KEY,
    session_id    uuid          NOT NULL REFERENCES digger.agent_sessions(session_id) ON DELETE CASCADE,
    role          digger.role   NOT NULL,
    content       jsonb         NOT NULL,
    token_counts  jsonb,
    created_at    timestamptz   NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION digger.recompute_priority_for_release(p_release_id bigint)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    max_tier digger.priority_tier;
BEGIN
    SELECT
        CASE
            WHEN bool_or(tier = 'must') THEN 'must'::digger.priority_tier
            WHEN bool_or(tier = 'nice') THEN 'nice'::digger.priority_tier
            WHEN bool_or(tier = 'eventually') THEN 'eventually'::digger.priority_tier
            ELSE 'eventually'::digger.priority_tier
        END
    INTO max_tier
    FROM digger.user_wantlist_priorities
    WHERE release_id = p_release_id;

    IF max_tier IS NULL THEN
        RETURN;
    END IF;

    UPDATE digger.release_scrape_state
       SET priority_tier = max_tier
     WHERE release_id = p_release_id
       AND priority_tier IS DISTINCT FROM max_tier;
END $$;

CREATE OR REPLACE FUNCTION digger.uwp_after_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM digger.recompute_priority_for_release(OLD.release_id);
        RETURN OLD;
    ELSE
        PERFORM digger.recompute_priority_for_release(NEW.release_id);
        IF TG_OP = 'UPDATE' AND OLD.release_id IS DISTINCT FROM NEW.release_id THEN
            PERFORM digger.recompute_priority_for_release(OLD.release_id);
        END IF;
        RETURN NEW;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_uwp_recompute ON digger.user_wantlist_priorities;
CREATE TRIGGER trg_uwp_recompute
AFTER INSERT OR UPDATE OR DELETE ON digger.user_wantlist_priorities
FOR EACH ROW EXECUTE FUNCTION digger.uwp_after_change();
"""
