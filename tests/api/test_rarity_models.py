"""Tests for rarity response models."""

from api.models import RarityListItem, RarityListResponse, RarityResponse, RaritySignal


class TestRaritySignal:
    def test_valid_signal(self) -> None:
        signal = RaritySignal(score=85.0, weight=0.30)
        assert signal.score == 85.0
        assert signal.weight == 0.30


class TestRarityResponse:
    def test_full_response(self) -> None:
        resp = RarityResponse(
            release_id=456,
            title="Test Release",
            artist="Test Artist",
            year=1968,
            rarity_score=87.2,
            tier="ultra-rare",
            hidden_gem_score=72.1,
            breakdown={
                "pressing_scarcity": RaritySignal(score=95.0, weight=0.30),
                "label_catalog": RaritySignal(score=80.0, weight=0.15),
                "format_rarity": RaritySignal(score=70.0, weight=0.15),
                "temporal_scarcity": RaritySignal(score=92.0, weight=0.20),
                "graph_isolation": RaritySignal(score=65.0, weight=0.20),
            },
        )
        assert resp.rarity_score == 87.2
        assert resp.tier == "ultra-rare"
        assert resp.breakdown["pressing_scarcity"].score == 95.0


class TestRarityListItem:
    def test_list_item(self) -> None:
        item = RarityListItem(
            release_id=456,
            title="Test",
            artist="Artist",
            year=1968,
            rarity_score=87.2,
            tier="ultra-rare",
        )
        assert item.release_id == 456


class TestRarityListResponse:
    def test_list_response(self) -> None:
        resp = RarityListResponse(
            items=[
                RarityListItem(
                    release_id=1,
                    title="R1",
                    artist="A1",
                    year=2000,
                    rarity_score=50.0,
                    tier="scarce",
                )
            ],
            total=100,
            page=1,
            page_size=20,
        )
        assert len(resp.items) == 1
        assert resp.total == 100
