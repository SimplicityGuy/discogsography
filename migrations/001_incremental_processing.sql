-- Migration: Add incremental processing support
-- This migration adds tables to track processing state and changes

-- Table to track overall processing state for each data type
CREATE TABLE IF NOT EXISTS processing_state (
    id SERIAL PRIMARY KEY,
    data_type VARCHAR(50) NOT NULL UNIQUE,  -- 'artists', 'labels', 'releases', 'masters'
    last_processed_at TIMESTAMP WITH TIME ZONE,
    last_file_url VARCHAR(500),
    last_file_checksum VARCHAR(64),
    last_file_size BIGINT,
    total_records_processed BIGINT DEFAULT 0,
    processing_status VARCHAR(20) DEFAULT 'idle',  -- 'idle', 'processing', 'error'
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table to track individual record processing state
CREATE TABLE IF NOT EXISTS record_processing_state (
    id BIGSERIAL PRIMARY KEY,
    data_type VARCHAR(50) NOT NULL,
    record_id VARCHAR(100) NOT NULL,
    record_hash VARCHAR(64) NOT NULL,
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_modified_at TIMESTAMP WITH TIME ZONE,
    processing_version INTEGER DEFAULT 1,
    UNIQUE(data_type, record_id)
);

-- Index for efficient lookups
CREATE INDEX idx_record_processing_type_id ON record_processing_state(data_type, record_id);
CREATE INDEX idx_record_processing_hash ON record_processing_state(record_hash);
CREATE INDEX idx_record_processing_modified ON record_processing_state(last_modified_at);

-- Table to track changes between processing runs
CREATE TABLE IF NOT EXISTS data_changelog (
    id BIGSERIAL PRIMARY KEY,
    data_type VARCHAR(50) NOT NULL,
    record_id VARCHAR(100) NOT NULL,
    change_type VARCHAR(20) NOT NULL,  -- 'created', 'updated', 'deleted'
    old_hash VARCHAR(64),
    new_hash VARCHAR(64),
    changed_fields JSONB,  -- Store which fields changed
    change_detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processing_run_id UUID,
    processed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP WITH TIME ZONE
);

-- Index for efficient changelog queries
CREATE INDEX idx_changelog_type_processed ON data_changelog(data_type, processed);
CREATE INDEX idx_changelog_detected_at ON data_changelog(change_detected_at);
CREATE INDEX idx_changelog_run_id ON data_changelog(processing_run_id);

-- Table to track processing runs
CREATE TABLE IF NOT EXISTS processing_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    data_type VARCHAR(50) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'running',  -- 'running', 'completed', 'failed'
    records_processed BIGINT DEFAULT 0,
    records_created BIGINT DEFAULT 0,
    records_updated BIGINT DEFAULT 0,
    records_deleted BIGINT DEFAULT 0,
    error_message TEXT,
    metadata JSONB  -- Store additional run information
);

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to automatically update updated_at
CREATE TRIGGER update_processing_state_updated_at
    BEFORE UPDATE ON processing_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to get unprocessed changes
CREATE OR REPLACE FUNCTION get_unprocessed_changes(
    p_data_type VARCHAR DEFAULT NULL,
    p_limit INTEGER DEFAULT 1000
)
RETURNS TABLE (
    id BIGINT,
    data_type VARCHAR,
    record_id VARCHAR,
    change_type VARCHAR,
    old_hash VARCHAR,
    new_hash VARCHAR,
    changed_fields JSONB,
    change_detected_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.data_type,
        c.record_id,
        c.change_type,
        c.old_hash,
        c.new_hash,
        c.changed_fields,
        c.change_detected_at
    FROM data_changelog c
    WHERE
        c.processed = FALSE
        AND (p_data_type IS NULL OR c.data_type = p_data_type)
    ORDER BY c.change_detected_at
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON TABLE processing_state IS 'Tracks overall processing state for each Discogs data type';
COMMENT ON TABLE record_processing_state IS 'Tracks individual record processing state for incremental updates';
COMMENT ON TABLE data_changelog IS 'Tracks changes detected between processing runs';
COMMENT ON TABLE processing_runs IS 'Tracks individual processing run metadata';
