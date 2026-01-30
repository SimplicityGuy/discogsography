"""Tests for discogs module."""

from pathlib import Path
from typing import Any
from unittest.mock import Mock, mock_open, patch

import pytest

from extractor.pyextractor.discogs import (
    LocalFileInfo,
    S3FileInfo,
    _calculate_file_checksum,
    _load_metadata,
    _save_metadata,
    _validate_existing_file,
    download_discogs_data,
)


class TestDownloadDiscogsData:
    """Test download_discogs_data function."""

    @patch("extractor.pyextractor.discogs._download_file_from_discogs")
    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_successful_download(self, mock_scrape: Mock, mock_download: Mock, tmp_path: Path) -> None:
        """Test successful download of Discogs data."""
        # Mock scraping to return file list
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_masters.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_releases.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_CHECKSUM.txt", 0),
            ]
        }

        # Mock checksum file content
        empty_file_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        checksum_content = f"{empty_file_sha256} discogs_20240201_artists.xml.gz\n{empty_file_sha256} discogs_20240201_labels.xml.gz\n{empty_file_sha256} discogs_20240201_masters.xml.gz\n{empty_file_sha256} discogs_20240201_releases.xml.gz\n"

        # Mock download function to create files
        def mock_download_impl(s3_key: str, output_path: Path, **_: Any) -> None:
            if "CHECKSUM.txt" in s3_key:
                output_path.write_text(checksum_content)
            else:
                output_path.write_bytes(b"")

        mock_download.side_effect = mock_download_impl

        # Call function
        result = download_discogs_data(str(tmp_path))

        # Verify results
        assert len(result) == 5
        assert "discogs_20240201_CHECKSUM.txt" in result
        assert "discogs_20240201_artists.xml.gz" in result
        assert "discogs_20240201_labels.xml.gz" in result
        assert "discogs_20240201_masters.xml.gz" in result
        assert "discogs_20240201_releases.xml.gz" in result

        # Verify scraping was called
        assert mock_scrape.call_count == 1
        # Download should be called for checksum + data files
        assert mock_download.call_count >= 1

    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_empty_bucket(self, mock_scrape: Mock, tmp_path: Path) -> None:
        """Test handling of empty file list from Discogs website."""
        # Mock scraping to return empty dict
        mock_scrape.return_value = {}

        # Call function - should raise ValueError
        with pytest.raises(ValueError, match="No complete Discogs export found"):
            download_discogs_data(str(tmp_path))

    @patch("extractor.pyextractor.discogs._download_file_from_discogs")
    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_skip_non_xml_files(self, mock_scrape: Mock, mock_download: Mock, tmp_path: Path) -> None:
        """Test that only expected file types are processed from scraping."""
        # Mock scraping to return only valid discogs files
        # Web scraping filters for discogs pattern, so non-discogs files won't appear
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_masters.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_releases.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_CHECKSUM.txt", 0),
            ]
        }

        # Mock checksum content
        empty_file_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        checksum_content = f"{empty_file_sha256} discogs_20240201_artists.xml.gz\n{empty_file_sha256} discogs_20240201_labels.xml.gz\n{empty_file_sha256} discogs_20240201_masters.xml.gz\n{empty_file_sha256} discogs_20240201_releases.xml.gz\n"

        # Mock download
        def mock_download_impl(s3_key: str, output_path: Path, **_: Any) -> None:
            if "CHECKSUM.txt" in s3_key:
                output_path.write_text(checksum_content)
            else:
                output_path.write_bytes(b"")

        mock_download.side_effect = mock_download_impl

        # Function should succeed - web scraping only returns valid files
        result = download_discogs_data(str(tmp_path))
        assert len(result) == 5

    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_s3_connection_failure(self, mock_scrape: Mock, tmp_path: Path) -> None:
        """Test handling of website scraping failure."""
        mock_scrape.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Connection failed"):
            download_discogs_data(str(tmp_path))

    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_incomplete_export_skipped(self, mock_scrape: Mock, tmp_path: Path) -> None:
        """Test that incomplete exports are skipped."""
        # Mock scraping to return incomplete export (missing files)
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                # Missing masters and releases - incomplete export
            ]
        }

        with pytest.raises(ValueError, match="No complete Discogs export found"):
            download_discogs_data(str(tmp_path))

    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_missing_checksum_file(self, mock_scrape: Mock, tmp_path: Path) -> None:
        """Test handling of missing checksum file."""
        # Mock scraping to return files without checksum
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_masters.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_releases.xml.gz", 0),
                # No CHECKSUM.txt file
            ]
        }

        with pytest.raises(ValueError, match="No complete Discogs export found"):
            download_discogs_data(str(tmp_path))

    @patch("extractor.pyextractor.discogs._download_file_from_discogs")
    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_checksum_download_failure(self, mock_scrape: Mock, mock_download: Mock, tmp_path: Path) -> None:
        """Test handling of checksum file download failure."""
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_masters.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_releases.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_CHECKSUM.txt", 0),
            ]
        }

        # Make checksum download fail
        mock_download.side_effect = Exception("Download failed")

        with pytest.raises(ValueError, match="No complete Discogs export found"):
            download_discogs_data(str(tmp_path))

    @patch("extractor.pyextractor.discogs._download_file_from_discogs")
    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_malformed_checksum_file(self, mock_scrape: Mock, mock_download: Mock, tmp_path: Path) -> None:
        """Test handling of malformed checksum file."""
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_masters.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_releases.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_CHECKSUM.txt", 0),
            ]
        }

        # Mock download to create malformed checksum file
        def mock_download_impl(s3_key: str, output_path: Path, **_: Any) -> None:
            if "CHECKSUM.txt" in s3_key:
                # Write content that will cause exception when parsed
                output_path.write_bytes(b"\xff\xfe")  # Invalid UTF-8

        mock_download.side_effect = mock_download_impl

        with pytest.raises(ValueError, match="No complete Discogs export found"):
            download_discogs_data(str(tmp_path))

    @patch("extractor.pyextractor.discogs._download_file_from_discogs")
    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_data_file_download_failure(self, mock_scrape: Mock, mock_download: Mock, tmp_path: Path) -> None:
        """Test handling of data file download failure."""
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_masters.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_releases.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_CHECKSUM.txt", 0),
            ]
        }

        empty_file_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        checksum_content = f"{empty_file_sha256} discogs_20240201_artists.xml.gz\n"

        # First call succeeds (checksum), subsequent calls fail (data files)
        def mock_download_impl(s3_key: str, output_path: Path, **_: Any) -> None:
            if "CHECKSUM.txt" in s3_key:
                output_path.write_text(checksum_content)
            else:
                raise Exception("Download failed")

        mock_download.side_effect = mock_download_impl

        with pytest.raises(Exception, match="Download failed"):
            download_discogs_data(str(tmp_path))

    @patch("extractor.pyextractor.discogs._download_file_from_discogs")
    @patch("extractor.pyextractor.discogs._scrape_file_list_from_discogs")
    def test_checksum_mismatch(self, mock_scrape: Mock, mock_download: Mock, tmp_path: Path) -> None:
        """Test handling of checksum mismatch."""
        mock_scrape.return_value = {
            "20240201": [
                S3FileInfo("data/2024/discogs_20240201_artists.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_labels.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_masters.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_releases.xml.gz", 0),
                S3FileInfo("data/2024/discogs_20240201_CHECKSUM.txt", 0),
            ]
        }

        # Use wrong checksum that won't match actual file content
        wrong_checksum = "0000000000000000000000000000000000000000000000000000000000000000"
        checksum_content = f"{wrong_checksum} discogs_20240201_artists.xml.gz\n{wrong_checksum} discogs_20240201_labels.xml.gz\n{wrong_checksum} discogs_20240201_masters.xml.gz\n{wrong_checksum} discogs_20240201_releases.xml.gz\n"

        def mock_download_impl(s3_key: str, output_path: Path, **_: Any) -> None:
            if "CHECKSUM.txt" in s3_key:
                output_path.write_text(checksum_content)
            else:
                output_path.write_bytes(b"test data")  # Different content = different checksum

        mock_download.side_effect = mock_download_impl

        with pytest.raises(ValueError, match="Checksum validation failed"):
            download_discogs_data(str(tmp_path))


class TestMetadataFunctions:
    """Test metadata helper functions."""

    def test_load_metadata_success(self, tmp_path: Path) -> None:
        """Test successful metadata loading."""
        metadata_file = tmp_path / ".discogs_metadata.json"
        metadata_file.write_text('{"test.xml.gz": {"path": "/tmp/test.xml.gz", "checksum": "abc123", "version": "20240201", "size": 1000}}')

        result = _load_metadata(tmp_path)

        assert len(result) == 1
        assert "test.xml.gz" in result
        assert result["test.xml.gz"].checksum == "abc123"
        assert result["test.xml.gz"].version == "20240201"
        assert result["test.xml.gz"].size == 1000

    def test_load_metadata_missing_file(self, tmp_path: Path) -> None:
        """Test loading metadata when file doesn't exist."""
        result = _load_metadata(tmp_path)
        assert result == {}

    def test_load_metadata_corrupted_file(self, tmp_path: Path) -> None:
        """Test loading metadata from corrupted file."""
        metadata_file = tmp_path / ".discogs_metadata.json"
        metadata_file.write_text("invalid json {{{")

        result = _load_metadata(tmp_path)
        assert result == {}

    def test_save_metadata_success(self, tmp_path: Path) -> None:
        """Test successful metadata saving."""
        metadata = {
            "test.xml.gz": LocalFileInfo(
                path=tmp_path / "test.xml.gz",
                checksum="abc123",
                version="20240201",
                size=1000,
            )
        }

        _save_metadata(tmp_path, metadata)

        metadata_file = tmp_path / ".discogs_metadata.json"
        assert metadata_file.exists()

    @patch("builtins.open", new_callable=mock_open)
    def test_save_metadata_write_failure(self, mock_file: Mock, tmp_path: Path) -> None:
        """Test save metadata when write fails."""
        mock_file.side_effect = OSError("Write failed")

        metadata = {
            "test.xml.gz": LocalFileInfo(
                path=tmp_path / "test.xml.gz",
                checksum="abc123",
                version="20240201",
                size=1000,
            )
        }

        # Should not raise exception, just log warning
        _save_metadata(tmp_path, metadata)


class TestChecksumFunctions:
    """Test checksum helper functions."""

    def test_calculate_file_checksum_success(self, tmp_path: Path) -> None:
        """Test successful checksum calculation."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"test content")

        result = _calculate_file_checksum(test_file)

        assert result is not None
        assert len(result) == 64  # SHA256 produces 64 hex characters

    def test_calculate_file_checksum_missing_file(self, tmp_path: Path) -> None:
        """Test checksum calculation on missing file."""
        test_file = tmp_path / "missing.txt"

        result = _calculate_file_checksum(test_file)

        assert result is None

    def test_validate_existing_file_success(self, tmp_path: Path) -> None:
        """Test validation of existing file with correct checksum."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"")
        expected_checksum = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        result = _validate_existing_file(test_file, expected_checksum)

        assert result is True

    def test_validate_existing_file_missing(self, tmp_path: Path) -> None:
        """Test validation of missing file."""
        test_file = tmp_path / "missing.txt"

        result = _validate_existing_file(test_file, "abc123")

        assert result is False

    def test_validate_existing_file_checksum_mismatch(self, tmp_path: Path) -> None:
        """Test validation when checksum doesn't match."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"test content")
        wrong_checksum = "0000000000000000000000000000000000000000000000000000000000000000"

        result = _validate_existing_file(test_file, wrong_checksum)

        assert result is False

    @patch("extractor.pyextractor.discogs._calculate_file_checksum")
    def test_validate_existing_file_checksum_error(self, mock_calculate: Mock, tmp_path: Path) -> None:
        """Test validation when checksum calculation fails."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"test")
        mock_calculate.return_value = None

        result = _validate_existing_file(test_file, "abc123")

        assert result is False
