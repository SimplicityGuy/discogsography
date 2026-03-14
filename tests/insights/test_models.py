"""Tests for insights Pydantic response models."""


class TestArtistCentralityItem:
    def test_valid(self) -> None:
        from insights.models import ArtistCentralityItem

        item = ArtistCentralityItem(rank=1, artist_id="a123", artist_name="Radiohead", edge_count=5432)
        assert item.rank == 1
        assert item.artist_name == "Radiohead"
        assert item.edge_count == 5432

    def test_serialization(self) -> None:
        from insights.models import ArtistCentralityItem

        item = ArtistCentralityItem(rank=1, artist_id="a123", artist_name="Radiohead", edge_count=5432)
        data = item.model_dump()
        assert data == {"rank": 1, "artist_id": "a123", "artist_name": "Radiohead", "edge_count": 5432}


class TestGenreTrendItem:
    def test_valid(self) -> None:
        from insights.models import GenreTrendItem

        item = GenreTrendItem(decade=1990, release_count=12345)
        assert item.decade == 1990
        assert item.release_count == 12345


class TestGenreTrendsResponse:
    def test_valid(self) -> None:
        from insights.models import GenreTrendItem, GenreTrendsResponse

        resp = GenreTrendsResponse(
            genre="Jazz",
            trends=[GenreTrendItem(decade=1960, release_count=5000)],
            peak_decade=1960,
        )
        assert resp.genre == "Jazz"
        assert resp.peak_decade == 1960
        assert len(resp.trends) == 1


class TestLabelLongevityItem:
    def test_valid(self) -> None:
        from insights.models import LabelLongevityItem

        item = LabelLongevityItem(
            rank=1,
            label_id="l456",
            label_name="Blue Note",
            first_year=1939,
            last_year=2025,
            years_active=86,
            total_releases=4500,
            peak_decade=1960,
            still_active=True,
        )
        assert item.years_active == 86
        assert item.still_active is True


class TestAnniversaryItem:
    def test_valid(self) -> None:
        from insights.models import AnniversaryItem

        item = AnniversaryItem(
            master_id="m789",
            title="OK Computer",
            artist_name="Radiohead",
            release_year=1997,
            anniversary=25,
        )
        assert item.anniversary == 25


class TestDataCompletenessItem:
    def test_valid(self) -> None:
        from insights.models import DataCompletenessItem

        item = DataCompletenessItem(
            entity_type="releases",
            total_count=15000000,
            with_image=12000000,
            with_year=14500000,
            with_country=13000000,
            with_genre=14000000,
            completeness_pct=89.67,
        )
        assert item.completeness_pct == 89.67


class TestComputationStatus:
    def test_valid(self) -> None:
        from insights.models import ComputationStatus

        status = ComputationStatus(
            insight_type="artist_centrality",
            last_computed=None,
            status="never_run",
        )
        assert status.status == "never_run"
