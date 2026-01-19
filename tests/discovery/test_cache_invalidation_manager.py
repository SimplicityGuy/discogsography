"""Tests for CacheInvalidationManager class."""

from datetime import UTC, datetime
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from discovery.cache_invalidation import (
    CacheInvalidationManager,
    EventType,
    InvalidationEvent,
    InvalidationRule,
    InvalidationScope,
)


class TestCacheInvalidationManagerInit:
    """Test CacheInvalidationManager initialization."""

    def test_manager_initialization(self) -> None:
        """Test manager initializes with correct default values."""
        manager = CacheInvalidationManager()

        assert manager.rules == []
        assert manager.handlers == {}
        assert manager.cache_backends == {}
        assert manager.invalidation_queue == []
        assert manager.batch_interval == 1.0
        assert manager.stats["events_processed"] == 0
        assert manager.stats["invalidations"] == 0
        assert manager.stats["rules_matched"] == 0
        assert manager.running is False


class TestCacheBackendRegistration:
    """Test cache backend registration."""

    def test_register_cache_backend(self) -> None:
        """Test registering a cache backend."""
        manager = CacheInvalidationManager()
        mock_cache = MagicMock()

        manager.register_cache_backend("redis", mock_cache)

        assert "redis" in manager.cache_backends
        assert manager.cache_backends["redis"] == mock_cache

    def test_register_multiple_backends(self) -> None:
        """Test registering multiple cache backends."""
        manager = CacheInvalidationManager()
        redis_cache = MagicMock()
        memcached_cache = MagicMock()

        manager.register_cache_backend("redis", redis_cache)
        manager.register_cache_backend("memcached", memcached_cache)

        assert len(manager.cache_backends) == 2
        assert manager.cache_backends["redis"] == redis_cache
        assert manager.cache_backends["memcached"] == memcached_cache


class TestRuleManagement:
    """Test invalidation rule management."""

    def test_add_single_event_rule(self) -> None:
        """Test adding rule with single event type."""
        manager = CacheInvalidationManager()

        rule = manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="artist:123",
        )

        assert isinstance(rule, InvalidationRule)
        assert EventType.ARTIST_UPDATED in rule.event_types
        assert rule.scope == InvalidationScope.EXACT
        assert rule.target == "artist:123"
        assert len(manager.rules) == 1

    def test_add_multiple_event_rule(self) -> None:
        """Test adding rule with multiple event types."""
        manager = CacheInvalidationManager()

        rule = manager.add_rule(
            event_types=[EventType.ARTIST_UPDATED, EventType.ARTIST_DELETED],
            scope=InvalidationScope.PREFIX,
            target="artist:",
        )

        assert len(rule.event_types) == 2
        assert EventType.ARTIST_UPDATED in rule.event_types
        assert EventType.ARTIST_DELETED in rule.event_types

    def test_rules_sorted_by_priority(self) -> None:
        """Test rules are sorted by priority (highest first)."""
        manager = CacheInvalidationManager()

        rule1 = manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="low_priority",
            priority=10,
        )
        rule2 = manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="high_priority",
            priority=100,
        )

        # Higher priority should come first
        assert manager.rules[0] == rule2
        assert manager.rules[1] == rule1


class TestEventEmission:
    """Test event emission and queueing."""

    @pytest.mark.asyncio
    async def test_emit_event_basic(self) -> None:
        """Test emitting a basic event."""
        manager = CacheInvalidationManager()

        await manager.emit_event(
            event_type=EventType.ARTIST_UPDATED,
            entity_id="artist_123",
        )

        assert len(manager.invalidation_queue) == 1
        event = manager.invalidation_queue[0]
        assert event.event_type == EventType.ARTIST_UPDATED
        assert event.entity_id == "artist_123"
        assert event.entity_data == {}
        assert manager.stats["events_processed"] == 1

    @pytest.mark.asyncio
    async def test_emit_event_with_data(self) -> None:
        """Test emitting event with entity data."""
        manager = CacheInvalidationManager()

        await manager.emit_event(
            event_type=EventType.RELEASE_UPDATED,
            entity_id="release_456",
            entity_data={"name": "Test Release", "year": 2024},
        )

        event = manager.invalidation_queue[0]
        assert event.entity_data["name"] == "Test Release"
        assert event.entity_data["year"] == 2024

    @pytest.mark.asyncio
    async def test_emit_multiple_events(self) -> None:
        """Test emitting multiple events queues them all."""
        manager = CacheInvalidationManager()

        await manager.emit_event(EventType.ARTIST_CREATED, "artist_1")
        await manager.emit_event(EventType.RELEASE_CREATED, "release_1")
        await manager.emit_event(EventType.LABEL_UPDATED, "label_1")

        assert len(manager.invalidation_queue) == 3
        assert manager.stats["events_processed"] == 3


class TestEventHandlers:
    """Test custom event handlers."""

    def test_add_event_handler(self) -> None:
        """Test adding a custom event handler."""
        manager = CacheInvalidationManager()

        def custom_handler(event: InvalidationEvent) -> None:
            pass

        manager.add_handler(EventType.ARTIST_UPDATED, custom_handler)

        assert len(manager.handlers[EventType.ARTIST_UPDATED]) == 1
        assert manager.handlers[EventType.ARTIST_UPDATED][0] == custom_handler

    @pytest.mark.asyncio
    async def test_sync_handler_execution(self) -> None:
        """Test synchronous handler is called during event processing."""
        manager = CacheInvalidationManager()
        handler_called = []

        def sync_handler(event: InvalidationEvent) -> None:
            handler_called.append(event.entity_id)

        manager.add_handler(EventType.ARTIST_UPDATED, sync_handler)
        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")

        await manager.process_events()

        assert handler_called == ["artist_123"]

    @pytest.mark.asyncio
    async def test_async_handler_execution(self) -> None:
        """Test asynchronous handler is called during event processing."""
        manager = CacheInvalidationManager()
        handler_called = []

        async def async_handler(event: InvalidationEvent) -> None:
            handler_called.append(event.entity_id)

        manager.add_handler(EventType.RELEASE_CREATED, async_handler)
        await manager.emit_event(EventType.RELEASE_CREATED, "release_456")

        await manager.process_events()

        assert handler_called == ["release_456"]

    @pytest.mark.asyncio
    async def test_handler_error_handling(self) -> None:
        """Test error in handler doesn't stop event processing."""
        manager = CacheInvalidationManager()

        def failing_handler(event: InvalidationEvent) -> None:
            raise ValueError("Handler failed")

        manager.add_handler(EventType.ARTIST_UPDATED, failing_handler)
        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")

        # Should not raise exception
        await manager.process_events()

        # Queue should be cleared even with error
        assert len(manager.invalidation_queue) == 0


class TestRuleApplication:
    """Test invalidation rule application."""

    @pytest.mark.asyncio
    async def test_matching_rule_applied(self) -> None:
        """Test matching rule is applied to event."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="artist:123",
        )

        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")
        await manager.process_events()

        assert manager.stats["rules_matched"] == 1

    @pytest.mark.asyncio
    async def test_non_matching_rule_ignored(self) -> None:
        """Test non-matching rule is not applied."""
        manager = CacheInvalidationManager()

        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="artist:123",
        )

        await manager.emit_event(EventType.RELEASE_UPDATED, "release_456")
        await manager.process_events()

        assert manager.stats["rules_matched"] == 0

    @pytest.mark.asyncio
    async def test_multiple_matching_rules_applied(self) -> None:
        """Test multiple matching rules are all applied."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="artist:123",
        )
        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.PREFIX,
            target="recommendations:",
        )

        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")
        await manager.process_events()

        assert manager.stats["rules_matched"] == 2


class TestTargetInterpolation:
    """Test target string interpolation."""

    def test_interpolate_entity_id(self) -> None:
        """Test entity_id placeholder is replaced."""
        manager = CacheInvalidationManager()
        event = InvalidationEvent(
            event_type=EventType.ARTIST_UPDATED,
            entity_id="artist_789",
            entity_data={},
            timestamp=datetime.now(UTC),
        )

        result = manager._interpolate_target("artist:{entity_id}", event)

        assert result == "artist:artist_789"

    def test_interpolate_entity_data_fields(self) -> None:
        """Test entity_data fields are replaced."""
        manager = CacheInvalidationManager()
        event = InvalidationEvent(
            event_type=EventType.RELEASE_UPDATED,
            entity_id="release_123",
            entity_data={"name": "Test Release", "year": 2024},
            timestamp=datetime.now(UTC),
        )

        result = manager._interpolate_target(
            "release:{entity_id}:{entity_data.name}:{entity_data.year}",
            event,
        )

        assert result == "release:release_123:Test Release:2024"

    def test_interpolate_pattern_unchanged(self) -> None:
        """Test Pattern objects are not interpolated."""
        manager = CacheInvalidationManager()
        event = InvalidationEvent(
            event_type=EventType.ARTIST_UPDATED,
            entity_id="artist_123",
            entity_data={},
            timestamp=datetime.now(UTC),
        )

        pattern = re.compile(r"artist:.*")
        result = manager._interpolate_target(pattern, event)

        assert result == pattern


class TestInvalidationScopes:
    """Test different invalidation scopes."""

    @pytest.mark.asyncio
    async def test_exact_scope_invalidation(self) -> None:
        """Test EXACT scope invalidation."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        mock_cache.delete = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="artist:{entity_id}",
        )

        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")
        await manager.process_events()

        mock_cache.delete.assert_called_once_with("artist:artist_123")

    @pytest.mark.asyncio
    async def test_prefix_scope_invalidation(self) -> None:
        """Test PREFIX scope invalidation."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        mock_cache.delete_pattern = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.PREFIX,
            target="artist:",
        )

        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")
        await manager.process_events()

        mock_cache.delete_pattern.assert_called_once_with("artist:*")

    @pytest.mark.asyncio
    async def test_pattern_scope_invalidation(self) -> None:
        """Test PATTERN scope invalidation."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        mock_cache.delete_pattern = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        pattern = re.compile(r"artist:\d+")
        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.PATTERN,
            target=pattern,
        )

        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")
        await manager.process_events()

        mock_cache.delete_pattern.assert_called_once()

    @pytest.mark.asyncio
    async def test_tag_scope_invalidation(self) -> None:
        """Test TAG scope invalidation."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        mock_cache.invalidate_tag = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        manager.add_rule(
            event_types=EventType.RELATIONSHIP_CREATED,
            scope=InvalidationScope.TAG,
            target="graph",
        )

        await manager.emit_event(EventType.RELATIONSHIP_CREATED, "rel_123")
        await manager.process_events()

        mock_cache.invalidate_tag.assert_called_once_with("graph")

    @pytest.mark.asyncio
    async def test_all_scope_invalidation(self) -> None:
        """Test ALL scope invalidation."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        mock_cache.clear = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        manager.add_rule(
            event_types=EventType.GENRE_UPDATED,
            scope=InvalidationScope.ALL,
            target="",
        )

        await manager.emit_event(EventType.GENRE_UPDATED, "genre_rock")
        await manager.process_events()

        mock_cache.clear.assert_called_once()


class TestStatistics:
    """Test statistics tracking."""

    def test_get_statistics_initial(self) -> None:
        """Test statistics returns correct initial values."""
        manager = CacheInvalidationManager()

        stats = manager.get_statistics()

        assert stats["events_processed"] == 0
        assert stats["invalidations"] == 0
        assert stats["rules_matched"] == 0
        assert stats["rules"] == 0
        assert stats["handlers"] == 0
        assert stats["backends"] == 0
        assert stats["queue_size"] == 0

    @pytest.mark.asyncio
    async def test_get_statistics_after_activity(self) -> None:
        """Test statistics updates after activity."""
        manager = CacheInvalidationManager()
        mock_cache = AsyncMock()
        manager.register_cache_backend("test_cache", mock_cache)

        manager.add_rule(
            event_types=EventType.ARTIST_UPDATED,
            scope=InvalidationScope.EXACT,
            target="artist:123",
        )

        def handler(event: InvalidationEvent) -> None:
            pass

        manager.add_handler(EventType.ARTIST_UPDATED, handler)

        await manager.emit_event(EventType.ARTIST_UPDATED, "artist_123")

        stats = manager.get_statistics()

        assert stats["events_processed"] == 1
        assert stats["rules"] == 1
        assert stats["handlers"] == 1
        assert stats["backends"] == 1
        assert stats["queue_size"] == 1


class TestDefaultRules:
    """Test default invalidation rules."""

    def test_setup_default_rules(self) -> None:
        """Test default rules are setup correctly."""
        manager = CacheInvalidationManager()

        manager.setup_default_rules()

        # Should have multiple default rules
        assert len(manager.rules) > 0

        # Verify some key default rules exist
        event_types = {et for rule in manager.rules for et in rule.event_types}
        assert EventType.ARTIST_UPDATED in event_types
        assert EventType.RELEASE_UPDATED in event_types
        assert EventType.RELATIONSHIP_CREATED in event_types
