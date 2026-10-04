"""Continuation tokens are redacted without changing normal access-log shape."""

import logging

import pytest
from uvicorn.logging import AccessFormatter

from common.snapshot_logging import SnapshotAccessFilter, redact_snapshot_url


@pytest.mark.parametrize("query", ["snapshot=secret", "%73napshot=secret", "snapshot=first&%73napshot=second&snapshot=new"])
def test_encoded_duplicate_keys_redact_all_values(query: str) -> None:
    url = redact_snapshot_url("/api/user/collection?" + query + "&limit=2")
    assert all(value not in url for value in ("secret", "first", "second"))
    assert "limit=2" in url
    record = logging.LogRecord("uvicorn.access", logging.INFO, "test", 1, '%s - "%s %s HTTP/%s" %d', ("owned", "GET", url, "1.1", 409), None)
    assert SnapshotAccessFilter().filter(record)
    assert "409" in AccessFormatter("%(request_line)s %(status_code)s", use_colors=False).format(record)


def test_httpx_url_object_redaction_and_legacy_controls() -> None:
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        "test",
        1,
        'HTTP Request: %s %s "%s %d %s"',
        ("GET", "http://owned/api/user/collection?%73napshot=secret", "HTTP/1.1", 200, "OK"),
        None,
    )
    assert SnapshotAccessFilter().filter(record)
    assert "secret" not in record.getMessage()
    for target in ("/api/user/collection?limit=1&offset=0", "/api/user/collection?snapshot=new", "/api/artists/1"):
        assert redact_snapshot_url(target) == target


def test_malformed_network_path_fails_closed_and_formatter_still_works() -> None:
    target = "//[?%73napshot=canary&snapshot=canary2"
    record = logging.LogRecord("uvicorn.access", logging.INFO, "test", 1, '%s - "%s %s HTTP/%s" %d', ("owned", "GET", target, "1.1", 404), None)
    assert SnapshotAccessFilter().filter(record)
    output = AccessFormatter("%(request_line)s %(status_code)s", use_colors=False).format(record)
    assert "canary" not in output and "404" in output
