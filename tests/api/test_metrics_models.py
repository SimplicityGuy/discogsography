"""Tests for metrics history Pydantic response models (Phase 3)."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from api.models import HealthHistoryResponse, QueueHistoryResponse


class TestQueueHistoryResponse:
    """Tests for QueueHistoryResponse model."""

    def test_valid_response(self):
        data = {
            "range": "1h",
            "granularity": "5min",
            "queues": {
                "graphinator-artists": {
                    "current": {"ready": 10, "unacked": 2},
                    "history": [{"ts": "2026-03-25T10:00:00Z", "ready": 8, "unacked": 1}],
                }
            },
            "dlq_summary": {
                "graphinator-artists-dlq": {"current": {"ready": 3}, "history": []},
            },
        }
        resp = QueueHistoryResponse(**data)
        assert resp.range == "1h"
        assert resp.granularity == "5min"
        assert "graphinator-artists" in resp.queues
        assert "graphinator-artists-dlq" in resp.dlq_summary

    def test_empty_queues(self):
        resp = QueueHistoryResponse(range="24h", granularity="15min", queues={}, dlq_summary={})
        assert resp.queues == {}
        assert resp.dlq_summary == {}

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            QueueHistoryResponse(range="1h", granularity="5min", queues={}, dlq_summary={}, extra_field="bad")

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            QueueHistoryResponse(range="1h", granularity="5min", queues={})


class TestHealthHistoryResponse:
    """Tests for HealthHistoryResponse model."""

    def test_valid_response(self):
        data = {
            "range": "7d",
            "granularity": "1hour",
            "services": {
                "api": {
                    "current": "healthy",
                    "uptime_pct": 99.8,
                    "history": [{"ts": "2026-03-25T10:00:00Z", "status": "healthy"}],
                }
            },
            "api_endpoints": {
                "/api/explore": {
                    "avg_latency_ms": 42.5,
                    "history": [{"ts": "2026-03-25T10:00:00Z", "avg_latency_ms": 40.1}],
                }
            },
        }
        resp = HealthHistoryResponse(**data)
        assert resp.range == "7d"
        assert resp.granularity == "1hour"
        assert "api" in resp.services
        assert "/api/explore" in resp.api_endpoints

    def test_empty_services(self):
        resp = HealthHistoryResponse(range="30d", granularity="6hour", services={}, api_endpoints={})
        assert resp.services == {}
        assert resp.api_endpoints == {}

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            HealthHistoryResponse(range="1h", granularity="5min", services={}, api_endpoints={}, bonus="nope")

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            HealthHistoryResponse(range="1h", granularity="5min", services={})
