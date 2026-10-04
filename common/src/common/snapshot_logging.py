"""Redact collection continuation tokens in supported server/client access logs."""

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def redact_snapshot_url(value: object) -> str:
    target = str(value)
    try:
        parts = urlsplit(target)
        fields = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=10_000)
    except ValueError:
        # Never throw into logging's raw-LogRecord diagnostic fallback.
        return "[REDACTED malformed request target]"
    if not any(key == "snapshot" and item != "new" for key, item in fields):
        return target
    query = urlencode([(key, "[REDACTED]" if key == "snapshot" and item != "new" else item) for key, item in fields])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


class SnapshotAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            args = list(record.args)
            if record.name == "uvicorn.access" and len(args) == 5:
                args[2] = redact_snapshot_url(args[2])
            elif record.name == "httpx" and len(args) == 5:
                args[1] = redact_snapshot_url(args[1])
            record.args = tuple(args)
        return True


def install_snapshot_log_redaction() -> None:
    for name in ("uvicorn.access", "httpx"):
        logger = logging.getLogger(name)
        if not any(isinstance(existing, SnapshotAccessFilter) for existing in logger.filters):
            logger.addFilter(SnapshotAccessFilter())
