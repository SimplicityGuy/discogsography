"""A scanner-range correction must never exempt an affected dependency upgrade."""

from pathlib import Path
import tomllib

from packaging.version import Version


ROOT = Path(__file__).resolve().parents[2]
ADVISORY = "GHSA-qwgh-2vcv-g2f7"


def test_block_buffer_advisory_exclusion_cannot_cover_affected_versions() -> None:
    """The upstream range is >=0.11.0,<0.12.1; only 0.10.4 was reviewed below it."""
    config = tomllib.loads((ROOT / "osv-scanner.toml").read_text())
    if ADVISORY not in {entry["id"] for entry in config.get("IgnoredVulns", [])}:
        return
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text())
    versions = [package["version"] for package in lock["package"] if package["name"] == "block-buffer"]
    assert versions, "remove the advisory exclusion when block-buffer leaves the graph"
    for version in versions:
        assert version == "0.10.4" or Version(version) >= Version("0.12.1"), (
            f"block-buffer {version} is affected or unreviewed: remove/reassess {ADVISORY}'s exclusion"
        )
