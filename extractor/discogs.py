import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from boto3 import client
from botocore import UNSIGNED
from botocore.config import Config
from orjson import OPT_INDENT_2, dumps, loads
from tqdm import tqdm


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


def download_discogs_data(output_directory: str) -> list[str]:
    logger.info("📥 Starting download of most recent Discogs data")
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load metadata about previously downloaded files
    metadata = _load_metadata(output_path)
    logger.info(f"📋 Loaded metadata for {len(metadata)} previously downloaded files")

    bucket = "discogs-data-dumps"
    try:
        s3 = client("s3", region_name="us-west-2", config=Config(signature_version=UNSIGNED))
        response = s3.list_objects_v2(Bucket=bucket, Prefix="data/")
        contents = response.get("Contents")
        if not contents:
            raise ValueError("No contents found in S3 bucket")
    except Exception as e:
        logger.error(f"❌ Failed to connect to S3 or fetch data: {e}")
        raise

    ids: dict[str, list[S3FileInfo]] = {}

    for content in contents:
        key = content["Key"]
        size = content["Size"]
        id = key.split("_")[1]
        if id not in ids:
            ids[id] = []
        ids[id].append(S3FileInfo(key, size))

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
            logger.info(f"🔍 Version {id} already downloaded, checking if files are valid...")
            # Check if all files for this version exist with correct checksums
            all_files_valid = True
            for filename in data:
                if "CHECKSUM" not in filename:
                    if filename not in metadata:
                        logger.info(f"⚠️ Missing file {filename} from metadata for version {id}")
                        all_files_valid = False
                        break
                    else:
                        # Check if file exists on disk
                        file_path = output_path / filename
                        if not file_path.exists():
                            logger.info(f"⚠️ File {filename} missing from disk for version {id}")
                            all_files_valid = False
                            break

            if all_files_valid:
                logger.info(f"✅ All files present for version {id}, will verify checksums...")

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
            with checksum_path.open("wb") as download_file:
                s3.download_fileobj(bucket, checksum_file.name, download_file)
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
            else:
                if file_path.exists():
                    logger.info(f"⚠️ File {filename} exists but checksum mismatch, will re-download")
                else:
                    logger.info(f"📄 File {filename} does not exist, will download")
                files_to_download.append(s3file)

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

            with (
                path.open("wb") as download_file,
                tqdm(
                    desc=desc,
                    bar_format=bar_format,
                    ncols=155,
                    total=s3file.size,
                    unit="B",
                    unit_scale=True,
                ) as t,
            ):
                try:
                    s3.download_fileobj(bucket, s3file.name, download_file, Callback=progress(t))
                except Exception as e:
                    logger.error(f"❌ Failed to download {s3file.name}: {e}")
                    raise

            # Calculate checksum for downloaded file
            calculated_checksum = _calculate_file_checksum(path)
            if calculated_checksum:
                checksums[filename] = calculated_checksum
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
                    path=file_path, checksum=checksum, version=id, size=file_path.stat().st_size
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
