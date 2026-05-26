"""Rate limiter singleton for the API service."""

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


# headers_enabled=True so 429 responses carry `Retry-After` (in seconds) — required
# by the GRUVAX contract and good practice for any throttled API.
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)


def bearer_token_key_func(request: Request) -> str:
    """Per-endpoint key_func for endpoints that want one rate-limit bucket per caller token.

    The Authorization header is hashed (not stored raw) so the rate-limit key never
    contains the plaintext token in slowapi telemetry, internal data structures, or
    error messages. If no Bearer token is present, falls back to the client IP so
    unauthenticated probes still get throttled.

    Used by `/api/user/collection` and friends, where both first-party JWTs and
    app tokens authenticate the same endpoint and need distinct buckets.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[len("bearer ") :].strip()
        if token:
            # 16 hex chars (64 bits) is plenty of entropy to keep buckets distinct
            # without filling slowapi's in-memory keyspace with full SHA-256 hashes.
            return "tok:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return "ip:" + get_remote_address(request)
