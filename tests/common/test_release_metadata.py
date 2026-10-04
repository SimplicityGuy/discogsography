"""First-label provenance and partial-pair contract."""

import pytest

from common.release_metadata import canonical_pair_metadata


@pytest.mark.parametrize("labels", [None, [], [{}], [None], [{"name": [], "catno": {}}], [{"name": "", "catno": ""}]])
def test_unusable_first_source_does_not_write_pair_members(labels: object) -> None:
    assert canonical_pair_metadata(labels) == {"canonical_pair_version": 1}


@pytest.mark.parametrize(
    "source,expected", [({"name": "A", "catno": "A-1"}, ("A", "A-1")), ({"name": "A"}, ("A", None)), ({"catno": "A-1"}, (None, "A-1"))]
)
def test_usable_source_writes_both_members(source: dict[str, str], expected: tuple[str | None, str | None]) -> None:
    assert canonical_pair_metadata([source, {"name": "B", "catno": "B-2"}]) == {
        "canonical_pair_version": 1,
        "canonical_pair_source": "first-label",
        "canonical_label": expected[0],
        "catalog_number": expected[1],
    }
