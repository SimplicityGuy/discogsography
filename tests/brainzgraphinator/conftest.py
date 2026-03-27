"""Pytest configuration for brainzgraphinator tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def disable_batch_mode():
    """Disable batch mode for all brainzgraphinator tests."""
    with patch("brainzgraphinator.brainzgraphinator.BATCH_MODE", False):
        yield


@pytest.fixture
def mock_neo4j_driver():
    """Create a mock Neo4j driver for testing."""
    driver = MagicMock()
    mock_session = AsyncMock()

    # Make session() return an async context manager
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = session_cm

    return driver


@pytest.fixture
def mock_tx():
    """Create a mock Neo4j transaction for testing enrichment functions."""
    tx = MagicMock()
    # Default: MATCH returns a result with a single record
    mock_result = MagicMock()
    mock_result.single.return_value = {"matched_id": 12345}
    tx.run.return_value = mock_result
    return tx


@pytest.fixture
def sample_artist_record():
    """Sample MusicBrainz artist record for testing."""
    return {
        "mbid": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
        "discogs_artist_id": 12345,
        "type": "Person",
        "gender": "Male",
        "begin_date": "1947-01-08",
        "end_date": "2016-01-10",
        "area": "London, England",
        "begin_area": "Brixton, London",
        "end_area": "New York City",
        "disambiguation": "David Robert Jones",
        "relations": [
            {
                "type": "member of band",
                "target_discogs_artist_id": 67890,
            },
            {
                "type": "collaboration",
                "target_discogs_artist_id": 11111,
            },
        ],
    }


@pytest.fixture
def sample_label_record():
    """Sample MusicBrainz label record for testing."""
    return {
        "mbid": "c595c289-47ce-4fba-b999-b87503e8cb71",
        "discogs_label_id": 54321,
        "type": "Original Production",
        "label_code": "1234",
        "begin_date": "1958",
        "end_date": None,
        "area": "New York",
    }


@pytest.fixture
def sample_release_record():
    """Sample MusicBrainz release record for testing."""
    return {
        "mbid": "a5d5abbc-fb46-427c-9e5f-8da2f0bdbb18",
        "discogs_release_id": 99999,
        "barcode": "724384952051",
        "status": "Official",
    }
