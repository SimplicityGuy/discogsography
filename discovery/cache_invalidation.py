"""Event-driven cache invalidation system.

This module provides intelligent cache invalidation based on data change events,
ensuring cache consistency while minimizing unnecessary invalidations.
"""

import asyncio
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from re import Pattern
from typing import Any

import structlog


logger = structlog.get_logger(__name__)


class EventType(str, Enum):
    """Types of data change events."""

    ARTIST_CREATED = "artist_created"
    ARTIST_UPDATED = "artist_updated"
    ARTIST_DELETED = "artist_deleted"

    RELEASE_CREATED = "release_created"
    RELEASE_UPDATED = "release_updated"
    RELEASE_DELETED = "release_deleted"

    LABEL_CREATED = "label_created"
    LABEL_UPDATED = "label_updated"
    LABEL_DELETED = "label_deleted"

    RELATIONSHIP_CREATED = "relationship_created"
    RELATIONSHIP_DELETED = "relationship_deleted"

    GENRE_UPDATED = "genre_updated"
    STYLE_UPDATED = "style_updated"


class InvalidationScope(str, Enum):
    """Scope of cache invalidation."""

    EXACT = "exact"  # Only exact cache key
    PREFIX = "prefix"  # All keys with prefix
    PATTERN = "pattern"  # Keys matching pattern
    TAG = "tag"  # All keys with specific tag
    ALL = "all"  # All cache entries


@dataclass
class InvalidationRule:
    """A cache invalidation rule."""

    event_types: set[EventType]
    scope: InvalidationScope
    target: str | Pattern[str]  # Cache key, prefix, or pattern
    delay: float = 0.0  # Delay before invalidation (seconds)
    priority: int = 0  # Higher priority rules execute first


@dataclass
class InvalidationEvent:
    """A cache invalidation event."""

    event_type: EventType
    entity_id: str
    entity_data: dict[str, Any]
    timestamp: datetime


class CacheInvalidationManager:
    """Manage event-driven cache invalidation."""

    def __init__(self) -> None:
        """Initialize cache invalidation manager."""
        # Invalidation rules
        self.rules: list[InvalidationRule] = []

        # Event handlers
        self.handlers: dict[EventType, list[Callable]] = defaultdict(list)

        # Cache backends
        self.cache_backends: dict[str, Any] = {}  # name -> cache instance

        # Invalidation queue for batch processing
        self.invalidation_queue: list[InvalidationEvent] = []
        self.batch_interval = 1.0  # Process queue every second

        # Statistics
        self.stats = {
            "events_processed": 0,
            "invalidations": 0,
            "rules_matched": 0,
        }

        self.running = False

    def register_cache_backend(self, name: str, cache_instance: Any) -> None:
        """Register a cache backend.

        Args:
            name: Backend name
            cache_instance: Cache instance with invalidate methods
        """
        self.cache_backends[name] = cache_instance
        logger.info("✅ Registered cache backend", name=name)

    def add_rule(
        self,
        event_types: list[EventType] | EventType,
        scope: InvalidationScope,
        target: str | Pattern[str],
        delay: float = 0.0,
        priority: int = 0,
    ) -> InvalidationRule:
        """Add an invalidation rule.

        Args:
            event_types: Event types that trigger this rule
            scope: Invalidation scope
            target: Target cache keys (key, prefix, or pattern)
            delay: Delay before invalidation
            priority: Rule priority

        Returns:
            Created rule
        """
        if isinstance(event_types, EventType):
            event_types = [event_types]

        rule = InvalidationRule(
            event_types=set(event_types),
            scope=scope,
            target=target,
            delay=delay,
            priority=priority,
        )

        self.rules.append(rule)

        # Sort by priority
        self.rules.sort(key=lambda r: r.priority, reverse=True)

        logger.info(
            "📋 Added invalidation rule",
            events=[e.value for e in rule.event_types],
            scope=scope,
            target=str(target),
        )

        return rule

    def add_handler(
        self,
        event_type: EventType,
        handler: Callable[[InvalidationEvent], None],
    ) -> None:
        """Add a custom event handler.

        Args:
            event_type: Event type to handle
            handler: Handler function
        """
        self.handlers[event_type].append(handler)
        logger.info("🎯 Added event handler", event_type=event_type)

    async def emit_event(
        self,
        event_type: EventType,
        entity_id: str,
        entity_data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a data change event.

        Args:
            event_type: Type of event
            entity_id: ID of affected entity
            entity_data: Optional entity data
        """
        event = InvalidationEvent(
            event_type=event_type,
            entity_id=entity_id,
            entity_data=entity_data or {},
            timestamp=datetime.now(UTC),
        )

        # Add to queue
        self.invalidation_queue.append(event)

        self.stats["events_processed"] += 1

        logger.debug(
            "📨 Event emitted",
            event_type=event_type,
            entity_id=entity_id,
        )

    async def process_events(self) -> None:
        """Process queued invalidation events."""
        if not self.invalidation_queue:
            return

        events = self.invalidation_queue.copy()
        self.invalidation_queue.clear()

        logger.debug("⚙️ Processing invalidation events", count=len(events))

        for event in events:
            # Run custom handlers
            for handler in self.handlers.get(event.event_type, []):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(
                        "❌ Error in event handler",
                        event_type=event.event_type,
                        error=str(e),
                    )

            # Apply invalidation rules
            await self._apply_rules(event)

    async def _apply_rules(self, event: InvalidationEvent) -> None:
        """Apply invalidation rules for an event.

        Args:
            event: Invalidation event
        """
        matched_rules = [rule for rule in self.rules if event.event_type in rule.event_types]

        if not matched_rules:
            return

        self.stats["rules_matched"] += len(matched_rules)

        for rule in matched_rules:
            # Apply delay if specified
            if rule.delay > 0:
                await asyncio.sleep(rule.delay)

            # Perform invalidation
            await self._invalidate(rule, event)

    async def _invalidate(
        self,
        rule: InvalidationRule,
        event: InvalidationEvent,
    ) -> None:
        """Perform cache invalidation.

        Args:
            rule: Invalidation rule
            event: Triggering event
        """
        # Interpolate entity data into target if needed
        target = self._interpolate_target(rule.target, event)

        logger.debug(
            "🗑️ Invalidating cache",
            scope=rule.scope,
            target=target,
            event_type=event.event_type,
        )

        # Invalidate across all backends
        for backend_name, cache_backend in self.cache_backends.items():
            try:
                if rule.scope == InvalidationScope.EXACT:
                    # EXACT scope requires string key
                    await self._invalidate_exact(cache_backend, str(target) if isinstance(target, Pattern) else target)

                elif rule.scope == InvalidationScope.PREFIX:
                    # PREFIX scope requires string prefix
                    await self._invalidate_prefix(cache_backend, str(target) if isinstance(target, Pattern) else target)

                elif rule.scope == InvalidationScope.PATTERN:
                    await self._invalidate_pattern(cache_backend, target)

                elif rule.scope == InvalidationScope.TAG:
                    # TAG scope requires string tag
                    await self._invalidate_tag(cache_backend, str(target) if isinstance(target, Pattern) else target)

                elif rule.scope == InvalidationScope.ALL:
                    await self._invalidate_all(cache_backend)

                self.stats["invalidations"] += 1

            except Exception as e:
                logger.error(
                    "❌ Cache invalidation error",
                    backend=backend_name,
                    error=str(e),
                )

    def _interpolate_target(
        self,
        target: str | Pattern[str],
        event: InvalidationEvent,
    ) -> str | Pattern[str]:
        """Interpolate event data into target string.

        Args:
            target: Target template
            event: Event with data

        Returns:
            Interpolated target
        """
        if isinstance(target, Pattern):
            return target

        # Replace placeholders like {entity_id}
        result = target
        result = result.replace("{entity_id}", event.entity_id)

        # Replace data fields like {entity_data.name}
        for key, value in event.entity_data.items():
            result = result.replace(f"{{entity_data.{key}}}", str(value))

        return result

    async def _invalidate_exact(self, cache: Any, key: str) -> None:
        """Invalidate exact cache key.

        Args:
            cache: Cache backend
            key: Cache key
        """
        if hasattr(cache, "delete"):
            await cache.delete(key)
        elif hasattr(cache, "invalidate"):
            await cache.invalidate(key)

    async def _invalidate_prefix(self, cache: Any, prefix: str) -> None:
        """Invalidate keys with prefix.

        Args:
            cache: Cache backend
            prefix: Key prefix
        """
        if hasattr(cache, "delete_pattern"):
            await cache.delete_pattern(f"{prefix}*")
        elif hasattr(cache, "invalidate_prefix"):
            await cache.invalidate_prefix(prefix)

    async def _invalidate_pattern(
        self,
        cache: Any,
        pattern: str | Pattern[str],
    ) -> None:
        """Invalidate keys matching pattern.

        Args:
            cache: Cache backend
            pattern: Key pattern
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        if hasattr(cache, "delete_pattern"):
            await cache.delete_pattern(pattern.pattern)
        elif hasattr(cache, "invalidate_pattern"):
            await cache.invalidate_pattern(pattern)

    async def _invalidate_tag(self, cache: Any, tag: str) -> None:
        """Invalidate keys with tag.

        Args:
            cache: Cache backend
            tag: Cache tag
        """
        if hasattr(cache, "invalidate_tag"):
            await cache.invalidate_tag(tag)

    async def _invalidate_all(self, cache: Any) -> None:
        """Invalidate all cache entries.

        Args:
            cache: Cache backend
        """
        if hasattr(cache, "clear"):
            await cache.clear()
        elif hasattr(cache, "flush_all"):
            await cache.flush_all()

    async def start(self) -> None:
        """Start the invalidation manager background task."""
        self.running = True
        logger.info("🚀 Starting cache invalidation manager...")

        # Fire-and-forget background task
        _ = asyncio.create_task(self._processing_loop())  # noqa: RUF006

    async def stop(self) -> None:
        """Stop the invalidation manager."""
        self.running = False
        logger.info("🛑 Stopping cache invalidation manager...")

    async def _processing_loop(self) -> None:
        """Background loop for processing events."""
        while self.running:
            try:
                await self.process_events()
                await asyncio.sleep(self.batch_interval)

            except Exception as e:
                logger.error("❌ Error in processing loop", error=str(e))
                await asyncio.sleep(5)  # Wait before retrying

    def get_statistics(self) -> dict[str, Any]:
        """Get invalidation statistics.

        Returns:
            Statistics dictionary
        """
        return {
            **self.stats,
            "rules": len(self.rules),
            "handlers": sum(len(h) for h in self.handlers.values()),
            "backends": len(self.cache_backends),
            "queue_size": len(self.invalidation_queue),
        }

    def setup_default_rules(self) -> None:
        """Setup default invalidation rules for common patterns."""
        # Artist updates invalidate artist-related caches
        self.add_rule(
            event_types=[EventType.ARTIST_UPDATED, EventType.ARTIST_DELETED],
            scope=InvalidationScope.PREFIX,
            target="artist:{entity_id}",
            priority=100,
        )

        # Artist updates also invalidate recommendations
        self.add_rule(
            event_types=[EventType.ARTIST_UPDATED],
            scope=InvalidationScope.PREFIX,
            target="recommendations:artist:{entity_id}",
            priority=90,
        )

        # Release updates invalidate release caches
        self.add_rule(
            event_types=[EventType.RELEASE_UPDATED, EventType.RELEASE_DELETED],
            scope=InvalidationScope.PREFIX,
            target="release:{entity_id}",
            priority=100,
        )

        # Relationship changes invalidate graph caches
        self.add_rule(
            event_types=[EventType.RELATIONSHIP_CREATED, EventType.RELATIONSHIP_DELETED],
            scope=InvalidationScope.TAG,
            target="graph",
            priority=80,
        )

        # Genre/style updates invalidate trending and analytics
        self.add_rule(
            event_types=[EventType.GENRE_UPDATED, EventType.STYLE_UPDATED],
            scope=InvalidationScope.PREFIX,
            target="analytics:",
            priority=70,
        )

        logger.info("✅ Setup default invalidation rules", rules=len(self.rules))
