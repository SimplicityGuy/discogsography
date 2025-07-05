"""Tests for discogs module."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from extractor.discogs import download_discogs_data


class TestDownloadDiscogsData:
    """Test download_discogs_data function."""

    @patch("extractor.discogs.client")
    def test_successful_download(self, mock_boto_client: Mock, tmp_path: Path) -> None:
        """Test successful download of Discogs data."""
        # Setup mock S3 client
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        # Mock list_objects_v2 response
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "discogs_20240201_artists.xml.gz", "ETag": '"abc123"', "Size": 1000000},
                {"Key": "discogs_20240201_labels.xml.gz", "ETag": '"def456"', "Size": 2000000},
                {"Key": "discogs_20240201_masters.xml.gz", "ETag": '"ghi789"', "Size": 3000000},
                {"Key": "discogs_20240201_releases.xml.gz", "ETag": '"jkl012"', "Size": 4000000},
                {"Key": "discogs_20240201_CHECKSUM.txt", "ETag": '"mno345"', "Size": 100},
            ]
        }

        # Mock checksum file content
        checksum_content = b"e3b0c44298fc1c149afbf4c8996fb924  discogs_20240201_artists.xml.gz\nd41d8cd98f00b204e9800998ecf84275e  discogs_20240201_labels.xml.gz\n1234567890abcdef1234567890abcdef  discogs_20240201_masters.xml.gz\nabcdef1234567890abcdef1234567890  discogs_20240201_releases.xml.gz\n"
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: checksum_content)}

        # Mock actual file downloads
        def mock_download(bucket: str, key: str, filename: str) -> None:  # noqa: ARG001
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            # Create files with content that matches the checksums
            if "CHECKSUM.txt" in key:
                Path(filename).write_bytes(checksum_content)
            else:
                # Create empty file - checksums won't match but that's OK for this test
                Path(filename).write_bytes(b"")

        mock_s3.download_file.side_effect = mock_download

        # Call function
        result = download_discogs_data(str(tmp_path))

        # Verify results
        assert len(result) == 5  # artists, labels, masters, releases, checksum
        assert any("artists.xml.gz" in path for path in result)
        assert any("labels.xml.gz" in path for path in result)
        assert any("masters.xml.gz" in path for path in result)
        assert any("releases.xml.gz" in path for path in result)
        assert any("CHECKSUM.txt" in path for path in result)

        # Verify S3 calls
        assert mock_s3.list_objects_v2.call_count == 1
        assert mock_s3.download_file.call_count == 5  # 4 data files + 1 checksum

    @patch("extractor.discogs.client")
    def test_empty_bucket(self, mock_boto_client: Mock, tmp_path: Path) -> None:
        """Test handling of empty S3 bucket."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        # Mock empty response
        mock_s3.list_objects_v2.return_value = {}

        # Call function
        result = download_discogs_data(str(tmp_path))

        # Should return empty list
        assert result == []

    @patch("extractor.discogs.client")
    def test_skip_non_xml_files(self, mock_boto_client: Mock, tmp_path: Path) -> None:
        """Test that non-XML files are skipped."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        # Mock response with mixed file types
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "discogs_20240201_artists.xml.gz", "ETag": '"abc123"', "Size": 1000000},
                {"Key": "discogs_20240201_labels.xml.gz", "ETag": '"def456"', "Size": 2000000},
                {"Key": "discogs_20240201_masters.xml.gz", "ETag": '"ghi789"', "Size": 3000000},
                {"Key": "discogs_20240201_releases.xml.gz", "ETag": '"jkl012"', "Size": 4000000},
                {"Key": "discogs_20240201_CHECKSUM.txt", "ETag": '"mno345"', "Size": 100},
                {
                    "Key": "readme.txt",  # Non-discogs file
                    "ETag": '"xyz789"',
                    "Size": 1000,
                },
            ]
        }

        # Mock checksum for all data files
        checksum_content = b"e3b0c44298fc1c149afbf4c8996fb924  discogs_20240201_artists.xml.gz\nd41d8cd98f00b204e9800998ecf84275e  discogs_20240201_labels.xml.gz\n1234567890abcdef1234567890abcdef  discogs_20240201_masters.xml.gz\nabcdef1234567890abcdef1234567890  discogs_20240201_releases.xml.gz\n"
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: checksum_content)}

        # Mock download
        def mock_download(bucket: str, key: str, filename: str) -> None:  # noqa: ARG001
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            Path(filename).write_bytes(b"")

        mock_s3.download_file.side_effect = mock_download

        # Call function
        result = download_discogs_data(str(tmp_path))

        # Should return all discogs files including checksum
        assert len(result) == 5  # 4 data files + checksum
        assert any("artists.xml.gz" in path for path in result)
        assert any("labels.xml.gz" in path for path in result)
        assert any("masters.xml.gz" in path for path in result)
        assert any("releases.xml.gz" in path for path in result)
        assert any("CHECKSUM.txt" in path for path in result)
        assert "readme.txt" not in str(result)
