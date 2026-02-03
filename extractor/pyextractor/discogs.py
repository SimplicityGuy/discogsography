import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from orjson import OPT_INDENT_2, dumps, loads
from tqdm import tqdm

if TYPE_CHECKING:
    from common.state_marker import StateMarker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class S3FileInfo:
    name: str
    size: int


@dataclass
class LocalFileInfo:
    path: Path
    checksum: str
    version: str
    size: int


def _load_metadata(output_directory: Path) -> dict[str, LocalFileInfo]:
    """Load metadata about previously downloaded files."""
    metadata_file = output_directory / ".discogs_metadata.json"
    if not metadata_file.exists():
        return {}

    try:
        with metadata_file.open("rb") as f:
            data = loads(f.read())

        metadata = {}
        for filename, info in data.items():
            metadata[filename] = LocalFileInfo(
                path=Path(info["path"]),
                checksum=info["checksum"],
                version=info["version"],
                size=info["size"],
            )
        return metadata
    except Exception as e:
        logger.warning(f"⚠️ Failed to load metadata: {e}")
        return {}


def _save_metadata(output_directory: Path, metadata: dict[str, LocalFileInfo]) -> None:
    """Save metadata about downloaded files."""
    metadata_file = output_directory / ".discogs_metadata.json"

    data = {}
    for filename, info in metadata.items():
        data[filename] = {
            "path": str(info.path),
            "checksum": info.checksum,
            "version": info.version,
            "size": info.size,
        }

    try:
        with metadata_file.open("wb") as f:
            f.write(dumps(data, option=OPT_INDENT_2))
    except Exception as e:
        logger.warning(f"⚠️ Failed to save metadata: {e}")


def _calculate_file_checksum(file_path: Path) -> str | None:
    """Calculate SHA256 checksum of a file."""
    try:
        hash_obj = sha256()
        with file_path.open("rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                hash_obj.update(byte_block)
        return hash_obj.hexdigest()
    except Exception as e:
        logger.error(f"❌ Failed to calculate checksum for {file_path}: {e}")
        return None


def _validate_existing_file(file_path: Path, expected_checksum: str) -> bool:
    """Validate that an existing file matches the expected checksum."""
    if not file_path.exists():
        return False

    actual_checksum = _calculate_file_checksum(file_path)
    if actual_checksum is None:
        return False

    return actual_checksum == expected_checksum


def _download_file_from_discogs(
    s3_key: str,
    output_path: Path,
    progress_callback: Callable[[int], None] | None = None,
) -> None:
    """
    Download a file from Discogs website proxy.

    Args:
        s3_key: The S3 key (e.g., "data/2026/discogs_20260101_artists.xml.gz")
        output_path: Local path to save the file
        progress_callback: Optional callback function called with bytes downloaded
    """
    from urllib.parse import quote

    # Construct Discogs download URL
    download_url = f"https://data.discogs.com/?download={quote(s3_key, safe='')}"

    # Download with streaming to handle large files
    response = requests.get(download_url, stream=True, timeout=300)
    response.raise_for_status()

    # Write to file with progress tracking
    with output_path.open("wb") as f:
        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(len(chunk))


def _scrape_file_list_from_discogs() -> dict[str, list[S3FileInfo]]:
    """
    Scrape the file list from Discogs website instead of using S3 listing.

    Returns a dictionary mapping version IDs to lists of S3FileInfo objects.
    """
    logger.info("🌐 Fetching file list from Discogs website...")

    try:
        # Step 1: Fetch the main page to get available years
        response = requests.get("https://data.discogs.com/", timeout=30)
        response.raise_for_status()
        html = response.text

        # Extract year directories (e.g., 2026/, 2025/, etc.)
        year_pattern = r'href="\?prefix=data%2F(\d{4})%2F"'
        years = re.findall(year_pattern, html)

        if not years:
            logger.error("❌ No year directories found on Discogs website")
            raise ValueError("Failed to parse year directories from Discogs website")

        # Sort years in descending order (most recent first)
        years = sorted(years, reverse=True)
        logger.info(f"📅 Found {len(years)} year directories, checking recent years...")

        # Step 2: Fetch files from recent years (check last 2 years)
        ids: dict[str, list[S3FileInfo]] = {}

        for year in years[:2]:  # Only check last 2 years for efficiency
            try:
                year_url = f"https://data.discogs.com/?prefix=data%2F{year}%2F"
                year_response = requests.get(year_url, timeout=30)
                year_response.raise_for_status()
                year_html = year_response.text

                # Extract file links from year directory
                # Pattern matches: ?download=data%2F2026%2Fdiscogs_20260101_artists.xml.gz
                file_pattern = r'\?download=data%2F\d{4}%2F(discogs_(\d{8})_[^"]+)'
                file_matches = re.findall(file_pattern, year_html)

                for filename, version_id in file_matches:
                    # URL decode the filename
                    from urllib.parse import unquote

                    filename = unquote(filename)

                    # Construct full S3 key
                    s3_key = f"data/{year}/{filename}"

                    if version_id not in ids:
                        ids[version_id] = []
                    # We don't have exact size from HTML, use 0 as placeholder
                    ids[version_id].append(S3FileInfo(s3_key, 0))

                if file_matches:
                    logger.info(
                        f"📋 Found {len(file_matches)} files in year {year} directory"
                    )

            except Exception as e:
                logger.warning(f"⚠️ Failed to fetch year {year} directory: {e}")
                continue

        if not ids:
            logger.error("❌ No files found on Discogs website")
            raise ValueError("Failed to parse file list from Discogs website")

        logger.info(f"📊 Found {len(ids)} unique versions from website")

        return ids

    except Exception as e:
        logger.error(f"❌ Failed to scrape file list from Discogs: {e}")
        raise


def get_latest_version() -> str | None:
    """Get the latest available Discogs data version without downloading.

    Returns:
        The version ID (e.g., "20260201") or None if not found
    """
    try:
        ids = _scrape_file_list_from_discogs()
        # Return the most recent version that has all required files
        for id in sorted(ids.keys(), reverse=True):
            prefix = f"discogs_{id}"
            required_files = [
                f"{prefix}_CHECKSUM.txt",
                f"{prefix}_artists.xml.gz",
                f"{prefix}_labels.xml.gz",
                f"{prefix}_masters.xml.gz",
                f"{prefix}_releases.xml.gz",
            ]
            if len(ids[id]) == len(required_files):
                return id
        return None
    except Exception as e:
        logger.error(f"❌ Failed to get latest version: {e}")
        return None


def download_discogs_data(
    output_directory: str,
    state_marker: "StateMarker",
    marker_path: Path,
) -> list[str]:
    logger.info("📥 Starting download of most recent Discogs data")
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load metadata about previously downloaded files
    metadata = _load_metadata(output_path)
    logger.info(f"📋 Loaded metadata for {len(metadata)} previously downloaded files")

    # Note: We no longer use S3 client directly since the bucket denies public GetObject access
    # Instead, we download files through the Discogs website proxy at https://data.discogs.com/

    # Scrape file list from Discogs website instead of S3 listing
    # This avoids the AccessDenied error from S3's ListBucket restriction
    try:
        ids = _scrape_file_list_from_discogs()
    except Exception as e:
        logger.error(f"❌ Failed to fetch file list: {e}")
        raise

    # Always try to use the most recent Discogs export first.
    for id in sorted(ids.keys(), reverse=True):
        # Check if we already have this version
        existing_version = None
        for local_info in metadata.values():
            if local_info.version == id:
                existing_version = id
                break

        prefix = f"discogs_{id}"
        data = [
            f"{prefix}_CHECKSUM.txt",
            f"{prefix}_artists.xml.gz",
            f"{prefix}_labels.xml.gz",
            f"{prefix}_masters.xml.gz",
            f"{prefix}_releases.xml.gz",
        ]

        # Ensure that the Discogs export for `id` has all of the data, skipping if it doesn't.
        if len(ids[id]) != len(data):
            continue

        if existing_version:
            logger.info(
                f"🔍 Version {id} already downloaded, checking if files are valid..."
            )
            # Check if all files for this version exist with correct checksums
            all_files_valid = True
            for filename in data:
                if "CHECKSUM" not in filename:
                    if filename not in metadata:
                        logger.info(
                            f"⚠️ Missing file {filename} from metadata for version {id}"
                        )
                        all_files_valid = False
                        break
                    else:
                        # Check if file exists on disk
                        file_path = output_path / filename
                        if not file_path.exists():
                            logger.info(
                                f"⚠️ File {filename} missing from disk for version {id}"
                            )
                            all_files_valid = False
                            break

            if all_files_valid:
                logger.info(
                    f"✅ All files present for version {id}, will verify checksums..."
                )

        # First, download the checksum file to get expected checksums
        checksum_file = None
        expected_checksums: dict[str, str] = {}

        for s3file in ids[id]:
            filename = Path(s3file.name).name
            if "CHECKSUM" in filename:
                checksum_file = s3file
                break

        if not checksum_file:
            logger.warning(f"⚠️ No checksum file found for version {id}, skipping")
            continue

        # Download checksum file first
        checksum_path = output_path / Path(checksum_file.name).name
        logger.info(f"⬇️ Downloading checksum file: {Path(checksum_file.name).name}")

        try:
            _download_file_from_discogs(checksum_file.name, checksum_path)
        except Exception as e:
            logger.error(f"❌ Failed to download checksum file: {e}")
            continue

        # Parse expected checksums
        try:
            with checksum_path.open("r", encoding="utf-8") as checksum_read_file:
                for line in checksum_read_file:
                    parts = line.strip().split(" ")
                    if len(parts) >= 2:
                        expected_checksums[parts[1]] = parts[0]
        except Exception as e:
            logger.error(f"❌ Failed to parse checksum file: {e}")
            continue

        # Check which files need to be downloaded
        files_to_download = []
        checksums: dict[str, str] = {}

        for s3file in ids[id]:
            filename = Path(s3file.name).name
            if "CHECKSUM" in filename:
                continue  # Already downloaded

            file_path = output_path / filename
            expected_checksum = expected_checksums.get(filename)

            if not expected_checksum:
                logger.warning(f"⚠️ No expected checksum found for {filename}")
                files_to_download.append(s3file)
                continue

            # Check if file exists and has correct checksum
            if _validate_existing_file(file_path, expected_checksum):
                logger.info(
                    f"✅ File {filename} already exists with correct checksum, skipping download"
                )
                checksums[filename] = expected_checksum

                # Track existing file in state marker
                if file_path.exists():
                    file_size = file_path.stat().st_size
                    state_marker.file_downloaded(file_size)
            else:
                if file_path.exists():
                    logger.info(
                        f"⚠️ File {filename} exists but checksum mismatch, will re-download"
                    )
                else:
                    logger.info(f"📄 File {filename} does not exist, will download")
                files_to_download.append(s3file)

        # Start download phase tracking
        # Count total files (excluding checksum)
        total_files = len([f for f in ids[id] if "CHECKSUM" not in Path(f.name).name])
        state_marker.start_download(total_files)
        state_marker.save(marker_path)

        # Download only the files that need downloading
        for s3file in files_to_download:
            filename = Path(s3file.name).name

            def progress(t: tqdm) -> Callable[[int], None]:
                def inner(bytes_amount: int) -> None:
                    t.update(bytes_amount)

                return inner

            path = output_path / filename
            desc = f"{filename:33}"
            bar_format = "{desc}{percentage:3.0f}%|{bar:80}{r_bar}"

            # Note: size from scraping is 0, so we don't know total size upfront
            # The progress bar will show bytes downloaded without percentage
            with tqdm(
                desc=desc,
                bar_format=bar_format,
                ncols=155,
                total=None,  # Unknown total size
                unit="B",
                unit_scale=True,
            ) as t:
                try:
                    _download_file_from_discogs(
                        s3file.name, path, progress_callback=progress(t)
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to download {s3file.name}: {e}")
                    raise

            # Calculate checksum for downloaded file
            calculated_checksum = _calculate_file_checksum(path)
            if calculated_checksum:
                checksums[filename] = calculated_checksum

                # Track file download in state marker
                if path.exists():
                    file_size = path.stat().st_size
                    state_marker.file_downloaded(file_size)
                    state_marker.save(marker_path)
            else:
                logger.error(f"❌ Failed to calculate checksum for {filename}")
                raise ValueError(f"Checksum calculation failed for {filename}")

        # Verify all checksums
        all_valid = True
        for filename, expected_checksum in expected_checksums.items():
            if filename in checksums:
                if checksums[filename] == expected_checksum:
                    logger.info(f"✅ Checksum verified for {filename:33}")
                else:
                    logger.error(f"❌ Checksum mismatch for {filename:33}")
                    all_valid = False
            else:
                logger.warning(f"⚠️ No checksum calculated for {filename}")
                all_valid = False

        if not all_valid:
            raise ValueError(f"Checksum validation failed for version {id}")

        # Update metadata
        new_metadata = {}
        for filename, checksum in checksums.items():
            file_path = output_path / filename
            if file_path.exists():
                new_metadata[filename] = LocalFileInfo(
                    path=file_path,
                    checksum=checksum,
                    version=id,
                    size=file_path.stat().st_size,
                )

        # Add checksum file to metadata
        if checksum_path.exists():
            checksum_hash = _calculate_file_checksum(checksum_path)
            if checksum_hash:
                new_metadata[checksum_path.name] = LocalFileInfo(
                    path=checksum_path,
                    checksum=checksum_hash,
                    version=id,
                    size=checksum_path.stat().st_size,
                )

        # Save updated metadata
        _save_metadata(output_path, new_metadata)

        # Complete download phase tracking
        state_marker.complete_download()
        state_marker.save(marker_path)

        logger.info(f"✅ Successfully validated version {id}")

        # Check if we're on a newer version than what was previously downloaded
        previous_versions = {info.version for info in metadata.values()}
        if previous_versions and id not in previous_versions:
            logger.info(
                f"🆕 Found newer version {id} (previously had: {sorted(previous_versions, reverse=True)[:1]})"
            )
        elif id in previous_versions:
            logger.info(f"✅ Version {id} is up to date")

        # Since the most recent Discogs export has been validated, stop trying to find a complete export.
        return data

    # If no complete export is found, raise an error
    raise ValueError("No complete Discogs export found")
