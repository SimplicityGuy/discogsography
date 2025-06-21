import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from boto3 import client
from botocore import UNSIGNED
from botocore.config import Config
from tqdm import tqdm

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class S3FileInfo:
    name: str
    size: int


def download_discogs_data(output_directory: str) -> list[str]:
    logger.info("Starting download of most recent Discogs data")

    bucket = "discogs-data-dumps"
    try:
        s3 = client("s3", region_name="us-west-2", config=Config(signature_version=UNSIGNED))
        response = s3.list_objects_v2(Bucket=bucket, Prefix="data/")
        contents = response.get("Contents")
        if not contents:
            raise ValueError("No contents found in S3 bucket")
    except Exception as e:
        logger.error(f"Failed to connect to S3 or fetch data: {e}")
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

        checksums: dict[str, str] = {}
        for s3file in ids[id]:
            filename = Path(s3file.name).name

            def progress(t: tqdm) -> Callable[[int], None]:
                def inner(bytes_amount: int) -> None:
                    t.update(bytes_amount)

                return inner

            path = Path(output_directory, filename)
            desc = f"{filename:33}"
            bar_format = "{desc}{percentage:3.0f}%|{bar:80}{r_bar}"
            with path.open("wb") as download_file:
                with tqdm(
                    desc=desc,
                    bar_format=bar_format,
                    ncols=155,
                    total=s3file.size,
                    unit="B",
                    unit_scale=True,
                ) as t:
                    try:
                        s3.download_fileobj(
                            bucket, s3file.name, download_file, Callback=progress(t)
                        )
                    except Exception as e:
                        logger.error(f"Failed to download {s3file.name}: {e}")
                        raise

            try:
                hash = sha256()
                with path.open("rb") as hash_file:
                    for byte_block in iter(lambda: hash_file.read(4096), b""):
                        hash.update(byte_block)
                    checksums[filename] = hash.hexdigest()
            except Exception as e:
                logger.error(f"Failed to calculate checksum for {filename}: {e}")
                raise

        checksum = Path(output_directory, data[0])
        with checksum.open("r") as checksum_file:
            while line := checksum_file.readline():
                parts = line.strip().split(" ")
                correct = "✅"
                if checksums[parts[1]] != parts[0]:
                    correct = "❌"
                    logger.error(f"Checksum mismatch for {parts[1]}")
                else:
                    logger.info(f"Checksum verified for {parts[1]}")
                print(f"  [{correct}]: checksum for {parts[1]:33}")

        # Since the most recent Discogs export has been downloaded, stop trying to find a complete export.
        return data

    # If no complete export is found, raise an error
    raise ValueError("No complete Discogs export found")
