"""Discogs collection and wantlist sync logic.

The canonical sync implementation lives in api/syncer.py.
This module re-exports sync_collection, sync_wantlist, and run_full_sync
from there, and retains _auth_header plus constants used by curator tests.

Key Discogs API gotchas:
- Collection: response key is 'releases', release ID at item['basic_information']['id']
- Wantlist:   response key is 'wants',    release ID at item['id']
"""

import os
import time

from api.syncer import run_full_sync, sync_collection, sync_wantlist  # noqa: F401
from common.oauth import _build_oauth_header, _hmac_sha1_signature as _hmac_sha1


DISCOGS_API_BASE = "https://api.discogs.com"
SYNC_DELAY_SECONDS = 0.5  # 0.5s between requests to stay under 60 req/min
PAGE_SIZE = 100


def _auth_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    token_secret: str,
) -> str:
    """Build a complete OAuth 1.0a Authorization header for a request."""
    nonce = os.urandom(16).hex()
    timestamp = str(int(time.time()))

    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    sig = _hmac_sha1(method, url, params, consumer_secret, token_secret)
    params["oauth_signature"] = sig
    return _build_oauth_header(params)
