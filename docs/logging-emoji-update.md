# Logging Emoji Documentation Update

## Summary

Updated logging emoji documentation in both `CLAUDE.md` and `README.md` to include new emoji introduced with the incremental processing feature.

## New Emoji Added

### 📡 Real-time Notifications

- **Usage**: Real-time notifications and changes consumer startup
- **Example**: `logger.info("📡 Started changes consumer for real-time notifications")`
- **Location**: `dashboard/dashboard.py:169`

### 🗑️ Deleted Records

- **Usage**: Detecting and reporting deleted records in incremental processing
- **Example**: `logger.info("🗑️ Detected {deleted_count} deleted {data_type} records")`
- **Location**: `common/processing_state.py:297`

## Files Updated

1. **CLAUDE.md** - Added new emoji to the technical documentation table
1. **README.md** - Added new emoji to the user-facing logging conventions table

## Context

These emoji were introduced as part of the incremental processing feature implementation, which includes:

- Real-time change notifications via WebSocket
- Change detection and deletion tracking
- ProcessingStateTracker for maintaining processing state

The emoji follow the project's established logging convention pattern of `logger.{level}("{emoji} {message}")` for visual clarity and consistency across all services.
