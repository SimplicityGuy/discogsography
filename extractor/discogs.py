from collections import namedtuple
from hashlib import sha256
from pathlib import Path
from typing import List

from boto3 import client
from botocore import UNSIGNED
from botocore.config import Config
from tqdm import tqdm

S3FileInfo = namedtuple("S3FileInfo", ["name", "size"])


def download_discogs_data(output_directory: str) -> List[str]:
    print(" -=: Download the most recent Discogs data :=- ")

    bucket = "discogs-data-dumps"
    s3 = client("s3", region_name="us-west-2", config=Config(signature_version=UNSIGNED))
    response = s3.list_objects_v2(Bucket=bucket, Prefix="data/")
    contents = response.get("Contents")

    ids = {}

    for content in contents:
        key = content["Key"]
        size = content["Size"]
        id = key.split("_")[1]
        if id not in ids.keys():
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

        checksums = {}
        for s3file in ids[id]:
            filename = s3file.name.split("/")[2]

            def progress(t):
                def inner(bytes_amount):
                    t.update(bytes_amount)

                return inner

            path = Path(output_directory, filename)
            desc = f"{filename:33}"
            bar_format = "{desc}{percentage:3.0f}%|{bar:80}{r_bar}"
            with path.open("wb") as f:
                with tqdm(
                    desc=desc,
                    bar_format=bar_format,
                    ncols=155,
                    total=s3file.size,
                    unit="B",
                    unit_scale=True,
                ) as t:
                    s3.download_fileobj(bucket, s3file.name, f, Callback=progress(t))

            hash = sha256()
            with path.open("rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    hash.update(byte_block)
                checksums[filename] = hash.hexdigest()

        checksum = Path(output_directory, data[0])
        with checksum.open("r") as f:
            while line := f.readline():
                parts = line.strip().split(" ")
                correct = "✅"
                if checksums[parts[1]] != parts[0]:
                    correct = "❌"
                print(f"  [{correct}]: checksum for {parts[1]:33}")

        # Since the most recent Discogs export has been downloaded, stop trying to find a complete export.
        return data
