"""Tests for brainzgraphinator module."""

import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aio_pika.abc import AbstractIncomingMessage
from neo4j.exceptions import ServiceUnavailable
from orjson import dumps
import pytest

import brainzgraphinator.brainzgraphinator as bgmod
from brainzgraphinator.brainzgraphinator import (
    HANDLERS,
    MB_RELATIONSHIP_MAP,
    MUSICBRAINZ_DATA_TYPES,
    PROCESSORS,
    check_all_consumers_idle,
    create_relationship_edges,
    enrich_artist,
    enrich_label,
    enrich_release,
    get_health_data,
    on_artist_message,
    on_label_message,
    on_release_message,
    signal_handler,
)


CLEAN_STATS = {"entities_enriched": 0, "entities_skipped_no_discogs_match": 0, "relationships_created": 0, "relationships_skipped_missing_side": 0}


# ── Health data tests ──────────────────────────────────────────────────────


class TestHealthData:
    """Tests for get_health_data."""

    @patch("brainzgraphinator.brainzgraphinator.graph", None)
    @patch("brainzgraphinator.brainzgraphinator.consumer_tags", {})
    @patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 0, "labels": 0, "releases": 0})
    def test_health_data_starting(self) -> None:
        """Health status is 'starting' when graph is None and no consumers registered."""
        data = get_health_data()
        assert data["status"] == "starting"
        assert data["service"] == "brainzgraphinator"
        assert data["current_task"] == "Initializing Neo4j connection"

    @patch("brainzgraphinator.brainzgraphinator.graph", MagicMock())
    @patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag-1"})
    @patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 0, "labels": 0, "releases": 0})
    @patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "releases": 0.0})
    @patch("brainzgraphinator.brainzgraphinator.completed_files", set())
    def test_health_data_healthy(self) -> None:
        """Health status is 'healthy' when graph is initialized."""
        data = get_health_data()
        assert data["status"] == "healthy"

    @patch("brainzgraphinator.brainzgraphinator.graph", MagicMock())
    @patch("brainzgraphinator.brainzgraphinator.consumer_tags", {})
    @patch("brainzgraphinator.brainzgraphinator.message_counts", {"artists": 10, "labels": 0, "releases": 0})
    @patch("brainzgraphinator.brainzgraphinator.last_message_time", {"artists": 0.0, "labels": 0.0, "releases": 0.0})
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

    def test_enrich_artist_with_discogs_match(self, mock_tx: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """Artist with discogs_artist_id gets enriched with all mb_ fields."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_artist(mock_tx, sample_artist_record)
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

    def test_enrich_artist_no_discogs_id_skips(self, mock_tx: MagicMock) -> None:
        """Artist with no discogs_artist_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_artist_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_artist(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    def test_enrich_artist_no_neo4j_match(self, mock_tx: MagicMock) -> None:
        """Artist with discogs_artist_id but no Neo4j match increments skip counter."""
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_tx.run.return_value = mock_result

        record = {"mbid": "abc", "discogs_artist_id": 12345}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_artist(mock_tx, record)
            assert result is True
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    def test_enrich_artist_with_relationships(self, mock_tx: MagicMock, sample_artist_record: dict[str, Any]) -> None:
        """Artist with relations triggers create_relationship_edges."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            enrich_artist(mock_tx, sample_artist_record)

        # First call is the MATCH/SET, subsequent calls are for relationships
        assert mock_tx.run.call_count >= 2

    def test_enrich_artist_missing_discogs_id_key(self, mock_tx: MagicMock) -> None:
        """Artist record missing discogs_artist_id key entirely is skipped."""
        record = {"mbid": "abc"}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_artist(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1


class TestEnrichLabel:
    """Tests for enrich_label."""

    def test_enrich_label_with_match(self, mock_tx: MagicMock, sample_label_record: dict[str, Any]) -> None:
        """Label with discogs_label_id gets enriched."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_label(mock_tx, sample_label_record)
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

    def test_enrich_label_no_discogs_id_skips(self, mock_tx: MagicMock) -> None:
        """Label with no discogs_label_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_label_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_label(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1

    def test_enrich_label_no_neo4j_match(self, mock_tx: MagicMock) -> None:
        """Label with discogs_label_id but no Neo4j match."""
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_tx.run.return_value = mock_result

        record = {"mbid": "abc", "discogs_label_id": 54321}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            enrich_label(mock_tx, record)
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1


class TestEnrichRelease:
    """Tests for enrich_release."""

    def test_enrich_release_with_match(self, mock_tx: MagicMock, sample_release_record: dict[str, Any]) -> None:
        """Release with discogs_release_id gets enriched."""
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_release(mock_tx, sample_release_record)
            assert result is True

        call_args = mock_tx.run.call_args_list[0]
        cypher = call_args[0][0]
        assert "SET r.mbid" in cypher
        assert "r.mb_barcode" in cypher
        assert "r.mb_status" in cypher
        assert "r.mb_updated_at" in cypher

    def test_enrich_release_no_discogs_id_skips(self, mock_tx: MagicMock) -> None:
        """Release with no discogs_release_id is deliberately skipped."""
        record = {"mbid": "abc", "discogs_release_id": None}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            result = enrich_release(mock_tx, record)
            assert result is True
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["entities_skipped_no_discogs_match"] == 1


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

    def test_create_edge_both_sides_matched(self, mock_tx: MagicMock) -> None:
        """Edge is created via MERGE when both source and target exist."""
        relations = [{"type": "member of band", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_called_once()
            cypher = mock_tx.run.call_args[0][0]
            assert "MERGE (a)-[r:MEMBER_OF]->(b)" in cypher
            assert bgmod.enrichment_stats["relationships_created"] == 1

    def test_create_edge_target_no_discogs_id_skips(self, mock_tx: MagicMock) -> None:
        """Edge with None target_discogs_artist_id is skipped."""
        relations = [{"type": "member of band", "target_discogs_artist_id": None}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["relationships_skipped_missing_side"] == 1

    def test_create_edge_unknown_type_skips(self, mock_tx: MagicMock) -> None:
        """Unknown relationship type is silently skipped."""
        relations = [{"type": "unknown_relationship", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_not_called()

    def test_create_edge_multiple_relations(self, mock_tx: MagicMock) -> None:
        """Multiple relations result in multiple MERGE calls."""
        relations = [
            {"type": "member of band", "target_discogs_artist_id": 67890},
            {"type": "collaboration", "target_discogs_artist_id": 11111},
            {"type": "teacher", "target_discogs_artist_id": 22222},
        ]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            create_relationship_edges(mock_tx, 12345, relations)
            assert mock_tx.run.call_count == 3
            assert bgmod.enrichment_stats["relationships_created"] == 3

    def test_edge_has_source_musicbrainz(self, mock_tx: MagicMock) -> None:
        """Edge SET includes source: 'musicbrainz'."""
        relations = [{"type": "founder", "target_discogs_artist_id": 67890}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            create_relationship_edges(mock_tx, 12345, relations)
            cypher = mock_tx.run.call_args[0][0]
            assert "r.source = 'musicbrainz'" in cypher

    def test_create_edge_missing_target_key(self, mock_tx: MagicMock) -> None:
        """Relation with missing target_discogs_artist_id key is skipped."""
        relations = [{"type": "member of band"}]
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            create_relationship_edges(mock_tx, 12345, relations)
            mock_tx.run.assert_not_called()
            assert bgmod.enrichment_stats["relationships_skipped_missing_side"] == 1


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
            mock_tx = MagicMock()
            mock_result = MagicMock()
            mock_result.single.return_value = {"matched_id": 12345}
            mock_tx.run.return_value = mock_result
            return func(mock_tx)

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
            patch("brainzgraphinator.brainzgraphinator.completed_files", {"artists", "labels", "releases"}),
        ):
            result = await check_all_consumers_idle()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_all_consumers_idle_false_consumers(self) -> None:
        """Returns False when consumers still active."""
        with (
            patch("brainzgraphinator.brainzgraphinator.consumer_tags", {"artists": "tag-1"}),
            patch("brainzgraphinator.brainzgraphinator.completed_files", {"artists", "labels", "releases"}),
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
        assert PROCESSORS["releases"] is enrich_release

    def test_handlers_map_has_all_types(self) -> None:
        """HANDLERS map covers all MUSICBRAINZ_DATA_TYPES."""
        for data_type in MUSICBRAINZ_DATA_TYPES:
            assert data_type in HANDLERS, f"Missing handler for: {data_type}"


# ── Additional edge case tests ───────────────────────────────────────────


class TestEdgeCases:
    """Additional edge case tests for completeness."""

    def test_enrich_artist_empty_relations(self, mock_tx: MagicMock) -> None:
        """Artist with empty relations list does not create edges."""
        record = {"mbid": "abc", "discogs_artist_id": 12345, "relations": []}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            enrich_artist(mock_tx, record)

        # Only the MATCH/SET call, no relationship calls
        assert mock_tx.run.call_count == 1

    def test_enrich_artist_no_relations_key(self, mock_tx: MagicMock) -> None:
        """Artist record without relations key works fine."""
        record = {"mbid": "abc", "discogs_artist_id": 12345}
        with patch.dict(bgmod.enrichment_stats, CLEAN_STATS):
            enrich_artist(mock_tx, record)

        assert mock_tx.run.call_count == 1

    @pytest.mark.asyncio
    @patch("brainzgraphinator.brainzgraphinator.shutdown_requested", False)
    async def test_on_label_message_processes(self, mock_neo4j_driver: MagicMock, sample_label_record: dict[str, Any]) -> None:
        """Label message is processed and acked."""
        mock_message = AsyncMock(spec=AbstractIncomingMessage)
        mock_message.body = dumps(sample_label_record)

        mock_session = await mock_neo4j_driver.session(database="neo4j").__aenter__()

        async def mock_tx_func(func: Any) -> Any:
            mock_tx = MagicMock()
            mock_result = MagicMock()
            mock_result.single.return_value = {"matched_id": 54321}
            mock_tx.run.return_value = mock_result
            return func(mock_tx)

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
            mock_tx = MagicMock()
            mock_result = MagicMock()
            mock_result.single.return_value = {"matched_id": 99999}
            mock_tx.run.return_value = mock_result
            return func(mock_tx)

        mock_session.execute_write.side_effect = mock_tx_func

        with patch("brainzgraphinator.brainzgraphinator.graph", mock_neo4j_driver):
            await on_release_message(mock_message)

        mock_message.ack.assert_called_once()

    def test_relationship_map_values_are_uppercase(self) -> None:
        """All relationship map values are valid Neo4j relationship type names."""
        for _mb_type, neo4j_type in MB_RELATIONSHIP_MAP.items():
            assert neo4j_type == neo4j_type.upper(), f"Neo4j type should be uppercase: {neo4j_type}"
            assert "_" in neo4j_type or neo4j_type.isalpha(), f"Neo4j type should use underscores: {neo4j_type}"
