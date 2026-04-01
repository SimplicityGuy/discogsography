"""Tests for brainzgraphinator module."""

import asyncio
import contextlib
import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aio_pika.abc import AbstractIncomingMessage
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from orjson import dumps
import pytest

import brainzgraphinator.brainzgraphinator as bgmod
from brainzgraphinator.brainzgraphinator import (
    HANDLERS,
    MB_RELATIONSHIP_MAP,
    MUSICBRAINZ_DATA_TYPES,
    PROCESSORS,
    check_all_consumers_idle,
    close_rabbitmq_connection,
    create_relationship_edges,
    enrich_artist,
    enrich_label,
    enrich_release,
    enrich_release_group,
    get_health_data,
    main,
    on_artist_message,
    on_label_message,
    on_release_message,
    periodic_queue_checker,
    schedule_consumer_cancellation,
    signal_handler,
)


CLEAN_STATS = {"entities_enriched": 0, "entities_skipped_no_discogs_match": 0, "relationships_created": 0, "relationships_skipped_missing_side": 0}


# ── Health data tests ──────────────────────────────────────────────────────


class TestHealthData:
    """Tests for get_health_data."""

    @patch("brainzgraphinator.brainzgraphinator.graph", None)
    @patch("brainzgraphinator.brainzgraphinator.consumer_tags", {})
    @patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0})
    def test_health_data_starting(self) -> None:
        """Health status is 'starting' when graph is None and no consumers registered."""
        data = get_health_data()
        assert data["status"] == "starting"
        assert data["service"] == "brainzgraphinator"
        assert data["current_task"] == "Initializing Neo4j connection"

    @patch("brainzgraphinator.brainzgraphinator.graph", MagicMock())
    @patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag-1"})
    @patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0})
    @patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0})
    @patch("brainzgraphinator.brainzgraphinator.completed_files", set())
    def test_health_data_healthy(self) -> None:
        """Health status is 'healthy' when graph is initialized."""
        data = get_health_data()
        assert data["status"] == "healthy"

    @patch("brainzgraphinator.brainzgraphinator.graph", MagicMock())
    @patch("brainzgraphinator.brainzgraphinator.consumer_tags", {})
    @patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 10, "labels": 0, "release-groups": 0, "releases": 0})
    @patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0})
    @patch("brainzgraphinator.brainzgraphinator.completed_files", set())
    @patch(
        "brainzgraphinator.brainzgraphinator.enrichment_stats",
        {"entities_enriched": 5, "entities_skipped_no_discogs_match": 3, "relationships_created": 2, "relationships_skipped_missing_side": 0},
    )
    def test_health_data_includes_enrichment_stats(self) -> None:
        """Health data includes enrichment_stats."""
        data = get_health_data()
        assert "enrichment_stats" in data
        assert data["enrichment_stats"]["entities_enriched"] == 5


# ── Enrichment function tests ─────────────────────────────────────────────


class TestEnrichArtist:
    """Tests for enrich_artist."""

    @pytest.mark.asyncio
    async def test_enrich_artist_with_discogs_match(self, mock_tx: AsyncMock, sample_artist_record: dict[str, Any]) -> None:
        """Artist with discogs_artist_id gets enriched with all mb_ fields."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_artist(mock_tx, sample_artist_record)
            assert result is True

        # Verify Cypher SET was called
        call_args = mock_tx.run.call_args_list[0]
        cypher = call_args[0][0]
        assert "SET a.mbid" in cypher
        assert "a.mb_type" in cypher
        assert "a.mb_gender" in cypher
        assert "a.mb_begin_date" in cypher
        assert "a.mb_end_date" in cypher
        assert "a.mb_area" in cypher
        assert "a.mb_begin_area" in cypher
        assert "a.mb_end_area" in cypher
        assert "a.mb_disambiguation" in cypher
        assert "a.mb_updated_at" in cypher

    @pytest.mark.asyncio
    async def test_enrich_artist_no_discogs_id_skips(self, mock_tx: AsyncMock) -> None:
        """Artist with no discogs_artist_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_artist_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_artist(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    @pytest.mark.asyncio
    async def test_enrich_artist_no_neo4j_match(self, mock_tx: AsyncMock) -> None:
        """Artist with discogs_artist_id but no Neo4j match increments skip counter."""
        mock_result = AsyncMock()
        mock_result.single.return_value = None
        mock_tx.run.return_value = mock_result

        record = {"mbid": "abc", "discogs_artist_id": 12345}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_artist(mock_tx, record)
            assert result is True
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    @pytest.mark.asyncio
    async def test_enrich_artist_with_relationships(self, mock_tx: AsyncMock, sample_artist_record: dict[str, Any]) -> None:
        """Artist with relations triggers create_relationship_edges."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await enrich_artist(mock_tx, sample_artist_record)

        # First call is the MATCH/SET, subsequent calls are for relationships
        assert mock_tx.run.call_count >= 2

    @pytest.mark.asyncio
    async def test_enrich_artist_missing_discogs_id_key(self, mock_tx: AsyncMock) -> None:
        """Artist record missing discogs_artist_id key entirely is skipped."""
        record = {"mbid": "abc"}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_artist(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1


class TestEnrichLabel:
    """Tests for enrich_label."""

    @pytest.mark.asyncio
    async def test_enrich_label_with_match(self, mock_tx: AsyncMock, sample_label_record: dict[str, Any]) -> None:
        """Label with discogs_label_id gets enriched."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_label(mock_tx, sample_label_record)
            assert result is True

        call_args = mock_tx.run.call_args_list[0]
        cypher = call_args[0][0]
        assert "SET l.mbid" in cypher
        assert "l.mb_type" in cypher
        assert "l.mb_label_code" in cypher
        assert "l.mb_begin_date" in cypher
        assert "l.mb_end_date" in cypher
        assert "l.mb_area" in cypher
        assert "l.mb_updated_at" in cypher

    @pytest.mark.asyncio
    async def test_enrich_label_no_discogs_id_skips(self, mock_tx: AsyncMock) -> None:
        """Label with no discogs_label_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_label_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_label(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    @pytest.mark.asyncio
    async def test_enrich_label_no_neo4j_match(self, mock_tx: AsyncMock) -> None:
        """Label with discogs_label_id but no Neo4j match."""
        mock_result = AsyncMock()
        mock_result.single.return_value = None
        mock_tx.run.return_value = mock_result

        record = {"mbid": "abc", "discogs_label_id": 54321}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await enrich_label(mock_tx, record)
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1


class TestEnrichRelease:
    """Tests for enrich_release."""

    @pytest.mark.asyncio
    async def test_enrich_release_with_match(self, mock_tx: AsyncMock, sample_release_record: dict[str, Any]) -> None:
        """Release with discogs_release_id gets enriched."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_release(mock_tx, sample_release_record)
            assert result is True

        call_args = mock_tx.run.call_args_list[0]
        cypher = call_args[0][0]
        assert "SET r.mbid" in cypher
        assert "r.mb_barcode" in cypher
        assert "r.mb_status" in cypher
        assert "r.mb_updated_at" in cypher

    @pytest.mark.asyncio
    async def test_enrich_release_no_discogs_id_skips(self, mock_tx: AsyncMock) -> None:
        """Release with no discogs_release_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_release_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_release(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    @pytest.mark.asyncio
    async def test_enrich_release_no_neo4j_match(self, mock_tx: AsyncMock) -> None:
        """Release with discogs_release_id but no Neo4j node increments skipped counter."""
        record = {"mbid": "abc", "discogs_release_id": 999}
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_tx.run = AsyncMock(return_value=mock_result)

        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_release(mock_tx, record)
            assert result is True
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1
            assert bgmod.enrichment_stats["entities_enriched"] == 0


# ── Release-group enrichment tests ────────────────────────────────────────


class TestEnrichReleaseGroup:
    """Tests for enrich_release_group."""

    @pytest.mark.asyncio
    async def test_enrich_release_group_with_match(self, mock_tx: AsyncMock, sample_release_group_record: dict[str, Any]) -> None:
        """Release-group with discogs_master_id gets enriched on Master node."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_release_group(mock_tx, sample_release_group_record)
            assert result is True

        call_args = mock_tx.run.call_args_list[0]
        cypher = call_args[0][0]
        assert "MATCH (m:Master" in cypher
        assert "SET m.mbid" in cypher
        assert "m.mb_type" in cypher
        assert "m.mb_secondary_types" in cypher
        assert "m.mb_first_release_date" in cypher
        assert "m.mb_updated_at" in cypher

    @pytest.mark.asyncio
    async def test_enrich_release_group_no_discogs_id_skips(self, mock_tx: AsyncMock) -> None:
        """Release-group with no discogs_master_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_master_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_release_group(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    @pytest.mark.asyncio
    async def test_enrich_release_group_no_neo4j_match(self, mock_tx: AsyncMock) -> None:
        """Release-group with discogs_master_id but no Neo4j Master node is skipped."""
        mock_tx.run.return_value.single.return_value = None
        record = {"mbid": "abc", "discogs_master_id": 99999}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = await enrich_release_group(mock_tx, record)
            assert result is True


# ── Relationship edge tests ───────────────────────────────────────────────


class TestRelationshipEdges:
    """Tests for create_relationship_edges and MB_RELATIONSHIP_MAP."""

    def test_relationship_map_defined(self) -> None:
        """All 8 expected relationship types are present in MB_RELATIONSHIP_MAP."""
        expected_types = [
            "member of band",
            "collaboration",
            "teacher",
            "tribute",
            "founder",
            "supporting musician",
            "subgroup",
            "artist rename",
        ]
        for mb_type in expected_types:
            assert mb_type in MB_RELATIONSHIP_MAP, f"Missing relationship type: {mb_type}"
        assert len(MB_RELATIONSHIP_MAP) == 8

    @pytest.mark.asyncio
    async def test_create_edge_both_sides_matched(self, mock_tx: AsyncMock) -> None:
        """Edge is created via MERGE when both source and target exist."""
        relations = [{"type": "member of band", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_called_once()
            cypher = mock_tx.run.call_args[0][0]
            assert "MERGE (a)-[r:MEMBER_OF]->(b)" in cypher
            assert bgmod.enrichment_stats["relationships_created"] == 1

    @pytest.mark.asyncio
    async def test_create_edge_target_no_discogs_id_skips(self, mock_tx: AsyncMock) -> None:
        """Edge with None target_discogs_artist_id is skipped."""
        relations = [{"type": "member of band", "target_discogs_artist_id": None}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["relationships_skipped_missing_side"] == 1

    @pytest.mark.asyncio
    async def test_create_edge_unknown_type_skips(self, mock_tx: AsyncMock) -> None:
        """Unknown relationship type is silently skipped."""
        relations = [{"type": "unknown_relationship", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_edge_multiple_relations(self, mock_tx: AsyncMock) -> None:
        """Multiple relations result in multiple MERGE calls."""
        relations = [
            {"type": "member of band", "target_discogs_artist_id": 67890},
            {"type": "collaboration", "target_discogs_artist_id": 11111},
            {"type": "teacher", "target_discogs_artist_id": 22222},
        ]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            assert mock_tx.run.call_count == 3
            assert bgmod.enrichment_stats["relationships_created"] == 3

    @pytest.mark.asyncio
    async def test_edge_has_source_musicbrainz(self, mock_tx: AsyncMock) -> None:
        """Edge SET includes source: 'musicbrainz'."""
        relations = [{"type": "founder", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            cypher = mock_tx.run.call_args[0][0]
            assert "r.source = 'musicbrainz'" in cypher

    @pytest.mark.asyncio
    async def test_create_edge_missing_target_key(self, mock_tx: AsyncMock) -> None:
        """Relation with missing target_discogs_artist_id key is skipped."""
        relations = [{"type": "member of band"}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["relationships_skipped_missing_side"] == 1

    @pytest.mark.asyncio
    async def test_create_edge_existing_relationship_updated(self, mock_tx: AsyncMock) -> None:
        """Existing relationship matched by MERGE counts as updated, not created."""
        # Mock: relationships_created=0, contains_updates=True (SET fired on existing rel)
        mock_summary = MagicMock()
        mock_summary.counters.relationships_created = 0
        mock_summary.counters.contains_updates = True
        mock_result = AsyncMock()
        mock_result.consume = AsyncMock(return_value=mock_summary)
        mock_tx.run = AsyncMock(return_value=mock_result)

        relations = [{"type": "member of band", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            assert bgmod.enrichment_stats.get("relationships_updated", 0) == 1
            assert bgmod.enrichment_stats["relationships_created"] == 0

    @pytest.mark.asyncio
    async def test_create_edge_both_nodes_missing(self, mock_tx: AsyncMock) -> None:
        """When neither node exists, relationship is skipped (no updates, no creation)."""
        # Mock: relationships_created=0, contains_updates=False (no rows produced)
        mock_summary = MagicMock()
        mock_summary.counters.relationships_created = 0
        mock_summary.counters.contains_updates = False
        mock_result = AsyncMock()
        mock_result.consume = AsyncMock(return_value=mock_summary)
        mock_tx.run = AsyncMock(return_value=mock_result)

        relations = [{"type": "member of band", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await create_relationship_edges(mock_tx, 12345, relations)
            assert bgmod.enrichment_stats["relationships_skipped_missing_side"] == 1
            assert bgmod.enrichment_stats["relationships_created"] == 0


# ── Message handling tests ────────────────────────────────────────────────


class TestMessageHandling:
    """Tests for message handlers."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_data_message_valid_data(self, mock_neo4j_driver: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """Valid artist message is processed and acked."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_artist_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()

        async def mock_tx_func(func: Any) -> Any:
            mock_tx = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single.return_value = {"matched_id": 12345}
            mock_counters = MagicMock()
            mock_counters.relationships_created = 1
            mock_counters.contains_updates = True
            mock_summary = MagicMock()
            mock_summary.counters = mock_counters
            mock_result.consume.return_value = mock_summary
            mock_tx.run.return_value = mock_result
            return await func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_data_message_file_complete(self) -> None:
        """file_complete control message is handled and acked."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps({"type": "file_complete", "total_processed": 100})

        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
            patch("brainzgraphinator.brainzgraphinator.queues", {}),
        ):
            await on_artist_message(mock_message)

        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_data_message_extraction_complete(self) -> None:
        """extraction_complete control message is handled and acked."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps({"type": "extraction_complete", "version": "2026-01"})

        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
            patch("brainzgraphinator.brainzgraphinator.queues", {}),
        ):
            await on_artist_message(mock_message)

        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_data_message_unparseable_body(self) -> None:
        """Unparseable message body results in nack with requeue."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = b"not valid json{{"

        with patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()):
            await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", True)
    async def test_on_data_message_shutdown_nacks(self) -> None:
        """Message received during shutdown is nacked with requeue."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)

        await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)
        mock_message.ack.assert_not_called()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_data_message_neo4j_error_requeues(self, mock_neo4j_driver: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """ServiceUnavailable from Neo4j results in nack with requeue."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_artist_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()
        mock_session.execute_write.side_effect = ServiceUnavailable("Neo4j is down")

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)


# ── Config tests ──────────────────────────────────────────────────────────


class TestConfig:
    """Tests for BrainzgraphinatorConfig."""

    def test_config_from_env_valid(self) -> None:
        """Config loads successfully with all required env vars."""
        from common.config import BrainzgraphinatorConfig

        env = {
            "NEO4J_HOST": "neo4j",
            "NEO4J_USERNAME": "neo4j",
            "NEO4J_PASSWORD": "test",
            "RABBITMQ_HOST": "rabbitmq",
            "RABBITMQ_USERNAME": "guest",
            "RABBITMQ_PASSWORD": "guest",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = BrainzgraphinatorConfig.from_env()

        assert cfg.neo4j_host == "bolt://neo4j:7687"
        assert cfg.neo4j_username == "neo4j"
        assert cfg.neo4j_password == "test"
        assert "amqp://" in cfg.amqp_connection

    def test_config_from_env_missing_raises(self) -> None:
        """Config raises ValueError when required env vars missing."""
        from common.config import BrainzgraphinatorConfig

        env = {
            "NEO4J_HOST": "",
            "NEO4J_USERNAME": "",
            "NEO4J_PASSWORD": "",
        }
        with patch.dict("os.environ", env, clear=False), pytest.raises(ValueError, match="Missing required"):
            BrainzgraphinatorConfig.from_env()


# ── Signal handler tests ─────────────────────────────────────────────────


class TestSignalHandler:
    """Tests for signal_handler."""

    def test_signal_handler_sets_shutdown(self) -> None:
        """signal_handler sets shutdown_requested to True."""
        original = bgmod.shutdown_requested
        try:
            bgmod.shutdown_requested = False
            signal_handler(signal.SIGTERM, None)
            assert bgmod.shutdown_requested is True
        finally:
            bgmod.shutdown_requested = original


# ── Consumer management tests ────────────────────────────────────────────


class TestConsumerManagement:
    """Tests for consumer management utilities."""

    @pytest.mark.asyncio
    async def test_check_all_consumers_idle_true(self) -> None:
        """Returns True when no consumers and all files completed."""
        with (
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", {"artists", "labels", "release-groups", "releases"}),
        ):
            result = await check_all_consumers_idle()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_all_consumers_idle_false_consumers(self) -> None:
        """Returns False when consumers still active."""
        with (
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag-1"}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", {"artists", "labels", "release-groups", "releases"}),
        ):
            result = await check_all_consumers_idle()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_all_consumers_idle_false_incomplete(self) -> None:
        """Returns False when not all files completed."""
        with (
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", {"artists"}),
        ):
            result = await check_all_consumers_idle()
        assert result is False


# ── PROCESSORS map tests ─────────────────────────────────────────────────


class TestProcessorsMap:
    """Tests for PROCESSORS lookup map."""

    def test_processors_map_has_all_types(self) -> None:
        """PROCESSORS map covers all MUSICBRAINZ_DATA_TYPES."""
        for data_type in MUSICBRAINZ_DATA_TYPES:
            assert data_type in PROCESSORS, f"Missing processor for: {data_type}"

    def test_processors_map_correct_functions(self) -> None:
        """PROCESSORS map maps to correct enrichment functions."""
        assert PROCESSORS["artists"] is enrich_artist
        assert PROCESSORS["labels"] is enrich_label
        assert PROCESSORS["release-groups"] is enrich_release_group
        assert PROCESSORS["releases"] is enrich_release

    def test_handlers_map_has_all_types(self) -> None:
        """HANDLERS map covers all MUSICBRAINZ_DATA_TYPES."""
        for data_type in MUSICBRAINZ_DATA_TYPES:
            assert data_type in HANDLERS, f"Missing handler for: {data_type}"


# ── Additional edge case tests ───────────────────────────────────────────


class TestEdgeCases:
    """Additional edge case tests for completeness."""

    @pytest.mark.asyncio
    async def test_enrich_artist_empty_relations(self, mock_tx: AsyncMock) -> None:
        """Artist with empty relations list does not create edges."""
        record = {"mbid": "abc", "discogs_artist_id": 12345, "relations": []}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await enrich_artist(mock_tx, record)

        # Only the MATCH/SET call, no relationship calls
        assert mock_tx.run.call_count == 1

    @pytest.mark.asyncio
    async def test_enrich_artist_no_relations_key(self, mock_tx: AsyncMock) -> None:
        """Artist record without relations key works fine."""
        record = {"mbid": "abc", "discogs_artist_id": 12345}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            await enrich_artist(mock_tx, record)

        assert mock_tx.run.call_count == 1

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_label_message_processes(self, mock_neo4j_driver: MagicMock, sample_label_record: dict[str, Any]) -> None:
        """Label message is processed and acked."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_label_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()

        async def mock_tx_func(func: Any) -> Any:
            mock_tx = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single.return_value = {"matched_id": 54321}
            mock_counters = MagicMock()
            mock_counters.relationships_created = 1
            mock_counters.contains_updates = True
            mock_summary = MagicMock()
            mock_summary.counters = mock_counters
            mock_result.consume.return_value = mock_summary
            mock_tx.run.return_value = mock_result
            return await func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_label_message(mock_message)

        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_release_message_processes(self, mock_neo4j_driver: MagicMock, sample_release_record: dict[str, Any]) -> None:
        """Release message is processed and acked."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_release_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()

        async def mock_tx_func(func: Any) -> Any:
            mock_tx = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single.return_value = {"matched_id": 99999}
            mock_counters = MagicMock()
            mock_counters.relationships_created = 1
            mock_counters.contains_updates = True
            mock_summary = MagicMock()
            mock_summary.counters = mock_counters
            mock_result.consume.return_value = mock_summary
            mock_tx.run.return_value = mock_result
            return await func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_release_message(mock_message)

        mock_message.ack.assert_called_once()

    def test_relationship_map_values_are_uppercase(self) -> None:
        """All relationship map values are valid Neo4j relationship type names."""
        for _mb_type, neo4j_type in MB_RELATIONSHIP_MAP.items():
            assert neo4j_type == neo4j_type.upper(), f"Neo4j type should be uppercase: {neo4j_type}"
            assert "_" in neo4j_type or neo4j_type.isalpha(), f"Neo4j type should use underscores: {neo4j_type}"


# ── Schedule consumer cancellation tests ─────────────────────────────────


class TestScheduleConsumerCancellation:
    """Tests for schedule_consumer_cancellation function."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_cancels_consumer_after_delay(self) -> None:
        """Test cancels consumer after specified delay."""
        mock_queue = AsyncMock()

        bgmod.consumer_tags = {"artists": "consumer-tag-123"}
        bgmod.consumer_cancel_tasks = {}

        await schedule_consumer_cancellation("artists", mock_queue)
        await asyncio.sleep(0.2)

        mock_queue.cancel.assert_called_once_with("consumer-tag-123", nowait=True)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.CONSUMER_CANCEL_DELAY", 0.1)
    async def test_cancels_existing_scheduled_task(self) -> None:
        """Test cancels existing scheduled task before creating new one."""
        mock_queue = AsyncMock()
        mock_existing_task = AsyncMock()

        bgmod.consumer_tags = {"artists": "consumer-tag-123"}
        bgmod.consumer_cancel_tasks = {"artists": mock_existing_task}

        await schedule_consumer_cancellation("artists", mock_queue)

        mock_existing_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.CONSUMER_CANCEL_DELAY", 0.1)
    @patch("brainzgraphinator.brainzgraphinator.check_all_consumers_idle")
    @patch("brainzgraphinator.brainzgraphinator.close_rabbitmq_connection")
    async def test_closes_connection_when_all_idle(self, mock_close: AsyncMock, mock_check_idle: AsyncMock) -> None:
        """Test closes RabbitMQ connection when all consumers idle."""
        mock_queue = AsyncMock()
        mock_check_idle.return_value = True

        bgmod.consumer_tags = {"artists": "consumer-tag-123"}
        bgmod.consumer_cancel_tasks = {}

        await schedule_consumer_cancellation("artists", mock_queue)
        await asyncio.sleep(0.2)

        mock_check_idle.assert_called_once()
        mock_close.assert_called_once()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.CONSUMER_CANCEL_DELAY", 0.01)
    async def test_cancel_exception_is_handled(self) -> None:
        """Test exception during consumer cancel is logged and handled."""
        mock_queue = AsyncMock()
        mock_queue.cancel.side_effect = Exception("Cancel failed")

        bgmod.consumer_tags = {"artists": "consumer-tag-123"}
        bgmod.consumer_cancel_tasks = {}

        await schedule_consumer_cancellation("artists", mock_queue)
        await asyncio.sleep(0.05)

        mock_queue.cancel.assert_called_once()
        assert "artists" not in bgmod.consumer_cancel_tasks

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.CONSUMER_CANCEL_DELAY", 10)
    async def test_cancel_during_shutdown_no_error(self) -> None:
        """Test that cancelling the task during shutdown does not raise."""
        mock_queue = AsyncMock()

        bgmod.consumer_tags = {"artists": "consumer-tag-123"}
        bgmod.consumer_cancel_tasks = {}

        await schedule_consumer_cancellation("artists", mock_queue)

        task = bgmod.consumer_cancel_tasks["artists"]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ── Close RabbitMQ connection tests ──────────────────────────────────────


class TestCloseRabbitMQConnection:
    """Tests for close_rabbitmq_connection function."""

    @pytest.mark.asyncio
    async def test_close_channel_and_connection(self) -> None:
        """Test closes both channel and connection."""
        mock_channel = AsyncMock()
        mock_connection = AsyncMock()

        bgmod.active_channel = mock_channel
        bgmod.active_connection = mock_connection

        await close_rabbitmq_connection()

        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()
        assert bgmod.active_channel is None
        assert bgmod.active_connection is None

    @pytest.mark.asyncio
    async def test_close_handles_channel_error(self) -> None:
        """Test handles errors when closing channel."""
        mock_channel = AsyncMock()
        mock_channel.close.side_effect = Exception("Close failed")
        mock_connection = AsyncMock()

        bgmod.active_channel = mock_channel
        bgmod.active_connection = mock_connection

        with patch("brainzgraphinator.brainzgraphinator.logger"):
            await close_rabbitmq_connection()

        assert bgmod.active_channel is None
        assert bgmod.active_connection is None

    @pytest.mark.asyncio
    async def test_close_handles_connection_error(self) -> None:
        """Test handles errors when closing connection."""
        mock_channel = AsyncMock()
        mock_connection = AsyncMock()
        mock_connection.close.side_effect = Exception("Connection close failed")

        bgmod.active_channel = mock_channel
        bgmod.active_connection = mock_connection

        with patch("brainzgraphinator.brainzgraphinator.logger"):
            await close_rabbitmq_connection()

        assert bgmod.active_channel is None
        assert bgmod.active_connection is None

    @pytest.mark.asyncio
    async def test_close_when_no_active_connections(self) -> None:
        """Test handles case when no active connections."""
        bgmod.active_channel = None
        bgmod.active_connection = None

        await close_rabbitmq_connection()

    @pytest.mark.asyncio
    async def test_outer_exception_logged(self) -> None:
        """Test that outer exception in close_rabbitmq_connection is logged."""
        bgmod.active_channel = None
        bgmod.active_connection = None

        with patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger:
            mock_logger.info.side_effect = Exception("Logger failed unexpectedly")

            await close_rabbitmq_connection()

        mock_logger.error.assert_called()
        error_str = " ".join(str(c) for c in mock_logger.error.call_args_list)
        assert "Error" in error_str


# ── Check consumers unexpectedly dead tests ──────────────────────────────


class TestCheckConsumersUnexpectedlyDead:
    """Tests for stuck state detection via health data."""

    def test_returns_stuck_when_consumers_dead(self) -> None:
        """Health data shows stuck when consumers have died unexpectedly."""
        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", {"artists"}),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 10, "labels": 0, "release-groups": 0, "releases": 0}),
            patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}),
        ):
            data = get_health_data()
            assert data["status"] == "unhealthy"
            assert "STUCK" in data["current_task"]

    def test_not_stuck_when_consumers_active(self) -> None:
        """Health data shows healthy when consumers are still active."""
        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag123"}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 10, "labels": 0, "release-groups": 0, "releases": 0}),
            patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}),
        ):
            data = get_health_data()
            assert data["status"] == "healthy"

    def test_not_stuck_when_no_messages_processed(self) -> None:
        """Health data not stuck when no messages have been processed yet."""
        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}),
            patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}),
        ):
            data = get_health_data()
            assert data["status"] == "healthy"


# ── Periodic queue checker tests ─────────────────────────────────────────


class TestPeriodicQueueChecker:
    """Tests for periodic_queue_checker function."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("brainzgraphinator.brainzgraphinator.STUCK_CHECK_INTERVAL", 0.05)
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_checks_queues_periodically(self) -> None:
        """Test periodically checks queues for messages."""
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.declaration_result.message_count = 0

        mock_rabbitmq_manager.connect.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue

        bgmod.rabbitmq_manager = mock_rabbitmq_manager
        bgmod.active_connection = None
        bgmod.active_channel = None
        bgmod.consumer_tags = {}
        bgmod.completed_files = {"artists", "labels", "release-groups", "releases"}

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.15)

        bgmod.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        assert mock_rabbitmq_manager.connect.called

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.QUEUE_CHECK_INTERVAL", 0.05)
    @patch("brainzgraphinator.brainzgraphinator.STUCK_CHECK_INTERVAL", 0.05)
    async def test_skips_check_when_connection_active(self) -> None:
        """Test skips check when connection is already active."""
        mock_rabbitmq_manager = AsyncMock()

        bgmod.rabbitmq_manager = mock_rabbitmq_manager
        bgmod.active_connection = AsyncMock()
        bgmod.shutdown_requested = False
        bgmod.consumer_tags = {"artists": "tag-1"}
        bgmod.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bgmod.completed_files = set()

        checker_task = asyncio.create_task(periodic_queue_checker())
        await asyncio.sleep(0.15)

        bgmod.shutdown_requested = True
        await asyncio.sleep(0.05)

        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker_task

        mock_rabbitmq_manager.connect.assert_not_called()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.STUCK_CHECK_INTERVAL", 0.01)
    async def test_stuck_state_triggers_recovery(self) -> None:
        """Test periodic_queue_checker detects stuck state and calls _recover_consumers."""
        bgmod.consumer_tags = {}
        bgmod.completed_files = {"artists"}
        bgmod.message_counts = {"artists": 10, "labels": 0, "release-groups": 0, "releases": 0}
        bgmod.active_connection = None
        bgmod.shutdown_requested = False

        recover_event = asyncio.Event()

        async def mock_recover() -> None:
            recover_event.set()
            bgmod.shutdown_requested = True

        with patch("brainzgraphinator.brainzgraphinator._recover_consumers", mock_recover):
            checker_task = asyncio.create_task(periodic_queue_checker())
            try:
                await asyncio.wait_for(recover_event.wait(), timeout=1.0)
            finally:
                bgmod.shutdown_requested = True
                checker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await checker_task

        assert recover_event.is_set()

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.STUCK_CHECK_INTERVAL", 0.01)
    @patch("brainzgraphinator.brainzgraphinator.QUEUE_CHECK_INTERVAL", 9999)
    async def test_timing_guard_prevents_frequent_checks(self) -> None:
        """Test timing guard continues when not enough time has passed."""
        bgmod.consumer_tags = {}
        bgmod.completed_files = {"artists", "labels", "release-groups", "releases"}
        bgmod.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bgmod.active_connection = None
        bgmod.shutdown_requested = False

        recover_call_count = [0]

        async def mock_recover() -> None:
            recover_call_count[0] += 1

        with patch("brainzgraphinator.brainzgraphinator._recover_consumers", mock_recover):
            checker_task = asyncio.create_task(periodic_queue_checker())
            await asyncio.sleep(0.08)
            bgmod.shutdown_requested = True
            await asyncio.sleep(0.02)
            checker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await checker_task

        assert recover_call_count[0] <= 2

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.STUCK_CHECK_INTERVAL", 0.01)
    async def test_periodic_queue_checker_exception_handling(self) -> None:
        """Test periodic_queue_checker handles exceptions in the loop."""
        bgmod.consumer_tags = {}
        bgmod.completed_files = {"artists", "labels", "release-groups", "releases"}
        bgmod.message_counts = {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}
        bgmod.active_connection = None
        bgmod.shutdown_requested = False

        call_count = [0]

        async def mock_recover() -> None:
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Recovery error")
            bgmod.shutdown_requested = True

        with (
            patch("brainzgraphinator.brainzgraphinator._recover_consumers", mock_recover),
            patch("brainzgraphinator.brainzgraphinator.QUEUE_CHECK_INTERVAL", 0.01),
        ):
            checker_task = asyncio.create_task(periodic_queue_checker())
            await asyncio.sleep(0.15)
            bgmod.shutdown_requested = True
            checker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await checker_task


# ── Progress reporter tests ──────────────────────────────────────────────


class TestProgressReporterFunction:
    """Tests for progress_reporter function."""

    @pytest.mark.asyncio
    async def test_progress_reporter_exits_immediately_on_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test progress_reporter exits when shutdown_requested is True."""
        monkeypatch.setattr(bgmod, "shutdown_requested", True)
        sleep_called = False

        async def mock_sleep(_: float) -> None:
            nonlocal sleep_called
            sleep_called = True

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)
        await bgmod.progress_reporter()
        assert not sleep_called

    @pytest.mark.asyncio
    async def test_progress_reporter_idle_mode_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test entering idle mode after startup timeout with no messages."""
        monkeypatch.setattr(bgmod, "shutdown_requested", False)
        monkeypatch.setattr(bgmod, "message_counts", {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0})
        monkeypatch.setattr(bgmod, "completed_files", set())
        monkeypatch.setattr(bgmod, "idle_mode", False)
        monkeypatch.setattr(bgmod, "STARTUP_IDLE_TIMEOUT", 0)
        monkeypatch.setattr(bgmod, "last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0})
        monkeypatch.setattr(bgmod, "consumer_tags", {})

        call_count = 0

        async def mock_sleep(_: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                monkeypatch.setattr(bgmod, "shutdown_requested", True)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)
        await bgmod.progress_reporter()
        assert bgmod.idle_mode is True

    @pytest.mark.asyncio
    async def test_progress_reporter_idle_mode_periodic_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test idle mode periodic logging when IDLE_LOG_INTERVAL passes."""
        monkeypatch.setattr(bgmod, "shutdown_requested", False)
        monkeypatch.setattr(bgmod, "message_counts", {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0})
        monkeypatch.setattr(bgmod, "completed_files", set())
        monkeypatch.setattr(bgmod, "idle_mode", True)
        monkeypatch.setattr(bgmod, "IDLE_LOG_INTERVAL", 0)
        monkeypatch.setattr(bgmod, "last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0})
        monkeypatch.setattr(bgmod, "consumer_tags", {})

        async def mock_sleep(_: float) -> None:
            monkeypatch.setattr(bgmod, "shutdown_requested", True)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)
        with patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger:
            await bgmod.progress_reporter()

        info_calls = " ".join(str(c) for c in mock_logger.info.call_args_list)
        assert "idle" in info_calls.lower()

    @pytest.mark.asyncio
    async def test_progress_reporter_skip_when_all_files_complete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test progress reporter skips when all files are complete."""
        monkeypatch.setattr(bgmod, "shutdown_requested", False)
        monkeypatch.setattr(bgmod, "message_counts", {"artists": 100, "labels": 50, "release-groups": 0, "releases": 200})
        monkeypatch.setattr(bgmod, "completed_files", set(MUSICBRAINZ_DATA_TYPES))
        monkeypatch.setattr(bgmod, "idle_mode", False)
        monkeypatch.setattr(bgmod, "last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0})
        monkeypatch.setattr(bgmod, "consumer_tags", {})

        async def mock_sleep(_: float) -> None:
            monkeypatch.setattr(bgmod, "shutdown_requested", True)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)
        with patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger:
            await bgmod.progress_reporter()

        info_calls = " ".join(str(c) for c in mock_logger.info.call_args_list)
        assert "progress" not in info_calls.lower()

    @pytest.mark.asyncio
    async def test_progress_reporter_reports_when_messages_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test progress reporter logs when total > 0."""
        monkeypatch.setattr(bgmod, "shutdown_requested", False)
        monkeypatch.setattr(bgmod, "message_counts", {"artists": 10, "labels": 5, "release-groups": 0, "releases": 0})
        monkeypatch.setattr(bgmod, "completed_files", set())
        monkeypatch.setattr(bgmod, "idle_mode", False)
        monkeypatch.setattr(bgmod, "STARTUP_IDLE_TIMEOUT", 99999)
        monkeypatch.setattr(bgmod, "last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0})
        monkeypatch.setattr(bgmod, "consumer_tags", {"artists": "tag-1"})

        async def mock_sleep(_: float) -> None:
            monkeypatch.setattr(bgmod, "shutdown_requested", True)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)
        with patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger:
            await bgmod.progress_reporter()

        info_calls = " ".join(str(c) for c in mock_logger.info.call_args_list)
        assert "progress" in info_calls.lower() or "enrichment" in info_calls.lower()

    @pytest.mark.asyncio
    async def test_progress_reporter_exits_idle_when_messages_arrive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When idle_mode is True but total > 0, idle_mode is set to False."""
        monkeypatch.setattr(bgmod, "shutdown_requested", False)
        monkeypatch.setattr(bgmod, "message_counts", {"artists": 5, "labels": 0, "release-groups": 0, "releases": 0})
        monkeypatch.setattr(bgmod, "completed_files", set())
        monkeypatch.setattr(bgmod, "idle_mode", True)
        monkeypatch.setattr(bgmod, "last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0})
        monkeypatch.setattr(bgmod, "consumer_tags", {"artists": "tag-1"})
        monkeypatch.setattr(bgmod, "STARTUP_IDLE_TIMEOUT", 99999)

        call_count = 0

        async def mock_sleep(_: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                monkeypatch.setattr(bgmod, "shutdown_requested", True)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)
        with patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger:
            await bgmod.progress_reporter()

        # idle_mode should have been set to False because total > 0
        assert bgmod.idle_mode is False
        # Should have logged the resumption message
        info_calls = " ".join(str(c) for c in mock_logger.info.call_args_list)
        assert "resuming" in info_calls.lower()


# ── Message handler edge case tests ──────────────────────────────────────


class TestMessageHandlerEdgeCases:
    """Tests for message handler edge cases."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_session_expired_requeues(self, mock_neo4j_driver: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """SessionExpired from Neo4j results in nack with requeue."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_artist_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()
        mock_session.execute_write.side_effect = SessionExpired("Session expired")

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_generic_exception_requeues(self, mock_neo4j_driver: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """Generic exception results in nack with requeue."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_artist_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()
        mock_session.execute_write.side_effect = RuntimeError("Something went wrong")

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_nack_failure_after_neo4j_error(self, mock_neo4j_driver: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """Nack failure after Neo4j error is handled gracefully."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_artist_record)
        mock_message.nack.side_effect = Exception("Nack failed")

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()
        mock_session.execute_write.side_effect = ServiceUnavailable("Neo4j down")

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_nack_failure_after_generic_error(self, mock_neo4j_driver: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """Nack failure after generic error is handled gracefully."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_artist_record)
        mock_message.nack.side_effect = Exception("Nack failed too")

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()
        mock_session.execute_write.side_effect = RuntimeError("Bad stuff")

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_graph_none_raises_runtime_error(self) -> None:
        """Message when graph is None raises RuntimeError, nacks with requeue."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps({"mbid": "abc", "discogs_artist_id": 12345})

        with patch("brainzgraphinator.brainzgraphinator.graph", None):
            await on_artist_message(mock_message)

        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_file_complete_adds_to_completed_files(self) -> None:
        """file_complete control message adds data_type to completed_files set."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps({"type": "file_complete", "total_processed": 100})

        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()) as mock_files,
            patch("brainzgraphinator.brainzgraphinator.queues", {}),
            patch("brainzgraphinator.brainzgraphinator.CONSUMER_CANCEL_DELAY", 0),
        ):
            await on_label_message(mock_message)
            assert "labels" in mock_files

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    @patch("brainzgraphinator.brainzgraphinator.CONSUMER_CANCEL_DELAY", 300)
    @patch("brainzgraphinator.brainzgraphinator.schedule_consumer_cancellation")
    async def test_file_complete_schedules_cancellation(self, mock_schedule: AsyncMock) -> None:
        """file_complete schedules consumer cancellation when delay > 0 and queue exists."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps({"type": "file_complete", "total_processed": 100})
        mock_queue = AsyncMock()

        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
            patch("brainzgraphinator.brainzgraphinator.queues", {"releases": mock_queue}),
        ):
            await on_release_message(mock_message)

        mock_schedule.assert_called_once_with("releases", mock_queue)

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_progress_interval_log(self, mock_neo4j_driver: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """Message handler logs at progress_interval milestones."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_artist_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()

        async def mock_tx_func(func: Any) -> Any:
            mock_tx = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single.return_value = {"matched_id": 12345}
            mock_counters = MagicMock()
            mock_counters.relationships_created = 1
            mock_counters.contains_updates = True
            mock_summary = MagicMock()
            mock_summary.counters = mock_counters
            mock_result.consume.return_value = mock_summary
            mock_tx.run.return_value = mock_result
            return await func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with (
            patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 99, "labels": 0, "release-groups": 0, "releases": 0}),
            patch("brainzgraphinator.brainzgraphinator.progress_interval", 100),
        ):
            await on_artist_message(mock_message)

        mock_message.ack.assert_called_once()


# ── Main function tests ──────────────────────────────────────────────────


class TestMainConfigError:
    """Test main() early return on BrainzgraphinatorConfig ValueError."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.signal.signal")
    @patch("brainzgraphinator.brainzgraphinator.setup_logging")
    @patch("brainzgraphinator.brainzgraphinator.HealthServer")
    @patch("brainzgraphinator.brainzgraphinator.BrainzgraphinatorConfig.from_env", side_effect=ValueError("bad config"))
    async def test_main_returns_on_config_error(
        self,
        _mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test main() returns after logging error when config raises ValueError."""
        mock_health_server.return_value = MagicMock()

        with (
            patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
            patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger,
        ):
            await main()

        error_calls = str(mock_logger.error.call_args_list)
        assert "Configuration error" in error_calls or "bad config" in error_calls


class TestMainNeo4jFailure:
    """Test main() early return on Neo4j connection failure."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.signal.signal")
    @patch("brainzgraphinator.brainzgraphinator.setup_logging")
    @patch("brainzgraphinator.brainzgraphinator.HealthServer")
    @patch("brainzgraphinator.brainzgraphinator.BrainzgraphinatorConfig.from_env")
    @patch("brainzgraphinator.brainzgraphinator.AsyncResilientNeo4jDriver")
    async def test_main_returns_on_neo4j_error(
        self,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test main() returns after logging error when Neo4j session raises."""
        mock_health_server.return_value = MagicMock()

        mock_config = MagicMock()
        mock_config.neo4j_host = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_from_env.return_value = mock_config

        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance

        def failing_session(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception("Neo4j connection refused")

        mock_neo4j_instance.session = MagicMock(side_effect=failing_session)

        with (
            patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
            patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger,
        ):
            await main()

        error_calls = str(mock_logger.error.call_args_list)
        assert "Neo4j" in error_calls or "Failed" in error_calls


class TestMainAmqpRetryExhausted:
    """Test main() when all RabbitMQ connection retry attempts are exhausted."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.signal.signal")
    @patch("brainzgraphinator.brainzgraphinator.setup_logging")
    @patch("brainzgraphinator.brainzgraphinator.HealthServer")
    @patch("brainzgraphinator.brainzgraphinator.BrainzgraphinatorConfig.from_env")
    @patch("brainzgraphinator.brainzgraphinator.AsyncResilientNeo4jDriver")
    @patch("brainzgraphinator.brainzgraphinator.AsyncResilientRabbitMQ")
    async def test_main_returns_when_connect_retries_exhausted(
        self,
        mock_rabbitmq_class: MagicMock,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test main() returns after exhausting all RabbitMQ connect retries."""
        mock_health_server.return_value = MagicMock()

        mock_config = MagicMock()
        mock_config.neo4j_host = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_config.amqp_connection = "amqp://guest:guest@localhost/"
        mock_from_env.return_value = mock_config

        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance
        mock_neo4j_instance.close = AsyncMock()

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"test": 1})
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_neo4j_instance.session = MagicMock(return_value=mock_cm)

        # RabbitMQ constructor succeeds, but connect() always raises
        mock_rabbitmq_instance = MagicMock()
        mock_rabbitmq_instance.connect = AsyncMock(side_effect=Exception("RabbitMQ connection refused"))
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        original_shutdown = bgmod.shutdown_requested
        try:
            bgmod.shutdown_requested = False
            with (
                patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
                patch("brainzgraphinator.brainzgraphinator.asyncio.sleep", AsyncMock(return_value=None)),
                patch("brainzgraphinator.brainzgraphinator.logger"),
            ):
                await main()

            # Should have tried max_startup_retries=5 times
            assert mock_rabbitmq_instance.connect.call_count == 5
        finally:
            bgmod.shutdown_requested = original_shutdown


class TestMainSuccessfulStartupAndShutdown:
    """Test main() successful startup and shutdown path."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.signal.signal")
    @patch("brainzgraphinator.brainzgraphinator.setup_logging")
    @patch("brainzgraphinator.brainzgraphinator.HealthServer")
    @patch("brainzgraphinator.brainzgraphinator.BrainzgraphinatorConfig.from_env")
    @patch("brainzgraphinator.brainzgraphinator.AsyncResilientNeo4jDriver")
    @patch("brainzgraphinator.brainzgraphinator.AsyncResilientRabbitMQ")
    async def test_main_successful_startup_and_shutdown(
        self,
        mock_rabbitmq_class: MagicMock,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test successful main execution with startup and graceful shutdown."""
        mock_health_server.return_value = MagicMock()

        mock_config = MagicMock()
        mock_config.neo4j_host = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_config.amqp_connection = "amqp://guest:guest@localhost/"
        mock_from_env.return_value = mock_config

        # Setup Neo4j
        mock_neo4j_instance = MagicMock()
        mock_neo4j_instance.close = AsyncMock()
        mock_neo4j_class.return_value = mock_neo4j_instance

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"test": 1})
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_neo4j_instance.session = MagicMock(return_value=mock_cm)

        # Setup RabbitMQ
        mock_rabbitmq_instance = MagicMock()
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        mock_connection = AsyncMock()
        mock_rabbitmq_instance.connect = AsyncMock(return_value=mock_connection)

        mock_channel = AsyncMock()
        mock_connection.channel = AsyncMock(return_value=mock_channel)
        mock_channel.set_qos = AsyncMock()
        mock_channel.declare_exchange = AsyncMock(return_value=AsyncMock())
        mock_channel.declare_queue = AsyncMock(return_value=AsyncMock())
        mock_connection.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection.__aexit__ = AsyncMock(return_value=None)

        original_shutdown = bgmod.shutdown_requested
        created_tasks: list[asyncio.Task[Any]] = []

        def mock_create_task(coro: Any) -> asyncio.Task[Any]:
            task = asyncio.get_event_loop().create_task(coro)
            created_tasks.append(task)
            return task

        try:
            with (
                patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
                patch("brainzgraphinator.brainzgraphinator.logger"),
                patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False),
                patch("asyncio.create_task", side_effect=mock_create_task),
            ):

                async def trigger_shutdown() -> None:
                    await asyncio.sleep(0.05)
                    bgmod.shutdown_requested = True

                shutdown_task = asyncio.ensure_future(trigger_shutdown())

                await main()
                await shutdown_task

            mock_neo4j_class.assert_called_once()
            mock_rabbitmq_class.assert_called_once()
            # Verify Neo4j driver is closed on shutdown
            mock_neo4j_instance.close.assert_awaited_once()
        finally:
            bgmod.shutdown_requested = original_shutdown
            for task in created_tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task


class TestMainStartupDelay:
    """Test main() startup delay."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.signal.signal")
    @patch("brainzgraphinator.brainzgraphinator.setup_logging")
    @patch("brainzgraphinator.brainzgraphinator.HealthServer")
    @patch("brainzgraphinator.brainzgraphinator.BrainzgraphinatorConfig.from_env", side_effect=ValueError("stop early"))
    async def test_main_startup_delay(
        self,
        _mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test that startup delay is applied before config load."""
        mock_health_server.return_value = MagicMock()
        sleep_calls: list[float] = []

        async def track_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        with (
            patch.dict("os.environ", {"STARTUP_DELAY": "3"}),
            patch("brainzgraphinator.brainzgraphinator.asyncio.sleep", side_effect=track_sleep),
            patch("brainzgraphinator.brainzgraphinator.logger"),
        ):
            await main()

        assert 3 in sleep_calls or 3.0 in sleep_calls


class TestMainAmqpConnectionNone:
    """Test main() when amqp_connection is None after retry loop."""

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.signal.signal")
    @patch("brainzgraphinator.brainzgraphinator.setup_logging")
    @patch("brainzgraphinator.brainzgraphinator.HealthServer")
    @patch("brainzgraphinator.brainzgraphinator.BrainzgraphinatorConfig.from_env")
    @patch("brainzgraphinator.brainzgraphinator.AsyncResilientNeo4jDriver")
    @patch("brainzgraphinator.brainzgraphinator.AsyncResilientRabbitMQ")
    async def test_main_returns_when_connection_none_after_shutdown(
        self,
        mock_rabbitmq_class: MagicMock,
        mock_neo4j_class: MagicMock,
        mock_from_env: MagicMock,
        mock_health_server: MagicMock,
        _mock_setup_logging: MagicMock,
        _mock_signal: MagicMock,
    ) -> None:
        """Test main() returns when shutdown requested during connection attempts."""
        mock_health_server.return_value = MagicMock()

        mock_config = MagicMock()
        mock_config.neo4j_host = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_config.amqp_connection = "amqp://guest:guest@localhost/"
        mock_from_env.return_value = mock_config

        mock_neo4j_instance = MagicMock()
        mock_neo4j_class.return_value = mock_neo4j_instance

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value={"test": 1})
        mock_session.run = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_neo4j_instance.session = MagicMock(return_value=mock_cm)

        # Make connect() set shutdown_requested so the while loop exits without connecting
        mock_rabbitmq_instance = MagicMock()

        async def connect_and_shutdown() -> None:
            bgmod.shutdown_requested = True
            raise Exception("Connection failed")

        mock_rabbitmq_instance.connect = AsyncMock(side_effect=connect_and_shutdown)
        mock_rabbitmq_class.return_value = mock_rabbitmq_instance

        original_shutdown = bgmod.shutdown_requested
        try:
            bgmod.shutdown_requested = False
            with (
                patch.dict("os.environ", {"STARTUP_DELAY": "0"}),
                patch("brainzgraphinator.brainzgraphinator.asyncio.sleep", AsyncMock(return_value=None)),
                patch("brainzgraphinator.brainzgraphinator.logger") as mock_logger,
            ):
                await main()

            error_calls = str(mock_logger.error.call_args_list)
            assert "AMQP" in error_calls or "connection" in error_calls.lower()
        finally:
            bgmod.shutdown_requested = original_shutdown


# ── Recover consumers tests ──────────────────────────────────────────────


class TestRecoverConsumers:
    """Tests for _recover_consumers function."""

    @pytest.mark.asyncio
    async def test_recover_no_messages_closes_connection(self) -> None:
        """Test _recover_consumers closes temp connection when no messages in queues."""
        from brainzgraphinator.brainzgraphinator import _recover_consumers

        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.declaration_result.message_count = 0

        mock_rabbitmq_manager.connect.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue

        bgmod.rabbitmq_manager = mock_rabbitmq_manager
        bgmod.active_connection = None
        bgmod.active_channel = None

        await _recover_consumers()

        mock_channel.close.assert_called_once()
        mock_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_with_messages_restarts_consumers(self) -> None:
        """Test _recover_consumers restarts consumers when messages found."""
        from brainzgraphinator.brainzgraphinator import _recover_consumers

        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        # First 4 declare_queue calls are passive checks, rest are declarations
        call_count = [0]

        def make_queue(*_args: Any, **_kwargs: Any) -> AsyncMock:
            q = AsyncMock()
            call_count[0] += 1
            # First 4 calls are passive checks (one per data type)
            if call_count[0] <= 4:
                if call_count[0] == 1:
                    q.declaration_result.message_count = 5  # artists has messages
                else:
                    q.declaration_result.message_count = 0
            return q

        mock_rabbitmq_manager.connect.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.side_effect = make_queue
        mock_channel.declare_exchange.return_value = AsyncMock()

        bgmod.rabbitmq_manager = mock_rabbitmq_manager
        bgmod.active_connection = None
        bgmod.active_channel = None
        bgmod.consumer_tags = {}
        bgmod.queues = {}
        bgmod.completed_files = set()
        bgmod.idle_mode = True

        await _recover_consumers()

        assert bgmod.active_connection is mock_connection
        assert bgmod.idle_mode is False

    @pytest.mark.asyncio
    async def test_recover_closes_existing_connection(self) -> None:
        """Test _recover_consumers closes existing connection before reconnecting."""
        from brainzgraphinator.brainzgraphinator import _recover_consumers

        mock_old_connection = AsyncMock()
        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_queue.declaration_result.message_count = 0

        mock_rabbitmq_manager.connect.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue

        bgmod.rabbitmq_manager = mock_rabbitmq_manager
        bgmod.active_connection = mock_old_connection
        bgmod.active_channel = None

        await _recover_consumers()

        mock_old_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_handles_connect_failure(self) -> None:
        """Test _recover_consumers handles RabbitMQ connection failure."""
        from brainzgraphinator.brainzgraphinator import _recover_consumers

        mock_rabbitmq_manager = AsyncMock()
        mock_rabbitmq_manager.connect.side_effect = Exception("Connection refused")

        bgmod.rabbitmq_manager = mock_rabbitmq_manager
        bgmod.active_connection = None
        bgmod.active_channel = None

        # Should not raise
        await _recover_consumers()

    @pytest.mark.asyncio
    async def test_recover_handles_queue_declaration_failure(self) -> None:
        """Test _recover_consumers handles failure during queue declaration."""
        from brainzgraphinator.brainzgraphinator import _recover_consumers

        mock_rabbitmq_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()

        mock_rabbitmq_manager.connect.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.side_effect = Exception("Queue declaration failed")

        bgmod.rabbitmq_manager = mock_rabbitmq_manager
        bgmod.active_connection = None
        bgmod.active_channel = None

        # Should not raise
        await _recover_consumers()

        # Should try to close the temp connection
        mock_channel.close.assert_called()


# ── Health data additional tests ─────────────────────────────────────────


class TestHealthDataAdditional:
    """Additional health data tests for coverage."""

    def test_health_timestamp_is_utc(self) -> None:
        """Test get_health_data timestamp uses UTC."""
        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {}),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}),
            patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
        ):
            data = get_health_data()
            assert data["timestamp"].endswith("+00:00")

    def test_health_data_active_processing(self) -> None:
        """Health data shows active task when recent messages received."""
        import time

        current = time.time()
        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag-1"}),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 50, "labels": 0, "release-groups": 0, "releases": 0}),
            patch(
                "brainzgraphinator.brainzgraphinator.last_message_time", {"artists": current, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}
            ),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
        ):
            data = get_health_data()
            assert "Enriching" in data["current_task"]

    def test_health_data_idle_waiting(self) -> None:
        """Health data shows idle when consumers active but no recent messages."""
        with (
            patch("brainzgraphinator.brainzgraphinator.graph", MagicMock()),
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag-1"}),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 0, "labels": 0, "release-groups": 0, "releases": 0}),
            patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
        ):
            data = get_health_data()
            assert "Idle" in data["current_task"]

    def test_health_data_unhealthy_no_graph(self) -> None:
        """Health data shows unhealthy when graph is None but messages were processed."""
        with (
            patch("brainzgraphinator.brainzgraphinator.graph", None),
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag-1"}),
            patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 10, "labels": 0, "release-groups": 0, "releases": 0}),
            patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "release-groups": 0.0, "releases": 0.0}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", set()),
        ):
            data = get_health_data()
            assert data["status"] == "unhealthy"
