"""Discogs OAuth 1.0a integration for discogsography auth service.

Implements Out-of-Band (OOB) OAuth flow:
1. Backend requests a token from Discogs with callback_uri="oob"
2. Request token is stored in Redis with a 10-minute TTL (CSRF protection)
3. User opens the Discogs authorization URL (in a popup or redirect)
4. User pastes the verifier code shown by Discogs into the app
5. Backend exchanges (request_token, verifier) for an access token + secret
6. Discogs identity is fetched (/oauth/identity) and stored in oauth_tokens table
"""

from base64 import b64encode
import hashlib
import hmac
import os
import time
from typing import Any
import urllib.parse

import httpx
import structlog


logger = structlog.get_logger(__name__)

DISCOGS_REQUEST_TOKEN_URL = "https://api.discogs.com/oauth/request_token"  # noqa: S105  # nosec B105
DISCOGS_AUTHORIZE_URL = "https://www.discogs.com/oauth/authorize"
DISCOGS_ACCESS_TOKEN_URL = "https://api.discogs.com/oauth/access_token"  # noqa: S105  # nosec B105
DISCOGS_IDENTITY_URL = "https://api.discogs.com/oauth/identity"

REDIS_OAUTH_STATE_TTL = 600  # 10 minutes in seconds
REDIS_STATE_PREFIX = "discogs:oauth:state:"


class DiscogsOAuthError(Exception):
    """Raised when a Discogs OAuth operation fails."""


def _oauth_escape(value: str) -> str:
    """Percent-encode a string for OAuth signatures (RFC 3986)."""
    return urllib.parse.quote(value, safe="")


def _build_oauth_header(params: dict[str, str]) -> str:
    """Build an OAuth Authorization header from a dict of parameters."""
    parts = [f'{k}="{_oauth_escape(v)}"' for k, v in sorted(params.items())]
    return "OAuth " + ", ".join(parts)


def _hmac_sha1_signature(
    method: str,
    url: str,
    oauth_params: dict[str, str],
    consumer_secret: str,
    token_secret: str = "",  # nosec B107
) -> str:
    """Generate an HMAC-SHA1 OAuth signature.

    Args:
        method: HTTP method (GET, POST, etc.)
        url: Request URL (without query string)
        oauth_params: OAuth parameters to include in the signature base
        consumer_secret: Discogs app consumer secret
        token_secret: OAuth token secret (empty for request token step)

    Returns:
        Base64-encoded HMAC-SHA1 signature string
    """
    # Collect and sort all parameters
    param_string = "&".join(f"{_oauth_escape(k)}={_oauth_escape(v)}" for k, v in sorted(oauth_params.items()))
    # Build the signature base string
    base_string = "&".join(
        [
            _oauth_escape(method.upper()),
            _oauth_escape(url),
            _oauth_escape(param_string),
        ]
    )
    # Build the signing key
    signing_key = f"{_oauth_escape(consumer_secret)}&{_oauth_escape(token_secret)}"
    # Compute HMAC-SHA1
    digest = hmac.new(signing_key.encode("ascii"), base_string.encode("ascii"), hashlib.sha1).digest()
    return b64encode(digest).decode("ascii")


async def request_oauth_token(
    consumer_key: str,
    consumer_secret: str,
    user_agent: str,
) -> dict[str, str]:
    """Request an OAuth request token from Discogs.

    Returns:
        dict with 'oauth_token' and 'oauth_token_secret'

    Raises:
        DiscogsOAuthError: if the request fails
    """
    nonce = os.urandom(16).hex()
    timestamp = str(int(time.time()))
    url = DISCOGS_REQUEST_TOKEN_URL

    oauth_params = {
        "oauth_callback": "oob",
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_version": "1.0",
    }

    signature = _hmac_sha1_signature("GET", url, oauth_params, consumer_secret)
    oauth_params["oauth_signature"] = signature

    headers = {
        "Authorization": _build_oauth_header(oauth_params),
        "User-Agent": user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        logger.debug("Discogs API error body", status=response.status_code, body=response.text)
        raise DiscogsOAuthError(f"Failed to get request token: HTTP {response.status_code}")

    params = dict(urllib.parse.parse_qsl(response.text))
    if "oauth_token" not in params or "oauth_token_secret" not in params:
        raise DiscogsOAuthError(f"Invalid response from Discogs: {response.text}")

    logger.info("✅ Discogs OAuth request token obtained")
    return {
        "oauth_token": params["oauth_token"],
        "oauth_token_secret": params["oauth_token_secret"],
    }


async def exchange_oauth_verifier(
    consumer_key: str,
    consumer_secret: str,
    oauth_token: str,
    oauth_token_secret: str,
    oauth_verifier: str,
    user_agent: str,
) -> dict[str, str]:
    """Exchange a verifier code for an OAuth access token.

    Args:
        consumer_key: Discogs app consumer key
        consumer_secret: Discogs app consumer secret
        oauth_token: Request token from the authorize step
        oauth_token_secret: Request token secret from the authorize step
        oauth_verifier: Verification code entered by the user
        user_agent: User-Agent string for Discogs API

    Returns:
        dict with 'oauth_token' (access token) and 'oauth_token_secret'

    Raises:
        DiscogsOAuthError: if the exchange fails
    """
    nonce = os.urandom(16).hex()
    timestamp = str(int(time.time()))
    url = DISCOGS_ACCESS_TOKEN_URL

    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_token": oauth_token,
        "oauth_verifier": oauth_verifier,
        "oauth_version": "1.0",
    }

    signature = _hmac_sha1_signature("POST", url, oauth_params, consumer_secret, oauth_token_secret)
    oauth_params["oauth_signature"] = signature

    headers = {
        "Authorization": _build_oauth_header(oauth_params),
        "User-Agent": user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers)

    if response.status_code != 200:
        logger.debug("Discogs API error body", status=response.status_code, body=response.text)
        raise DiscogsOAuthError(f"Failed to exchange verifier: HTTP {response.status_code}")

    params = dict(urllib.parse.parse_qsl(response.text))
    if "oauth_token" not in params or "oauth_token_secret" not in params:
        raise DiscogsOAuthError(f"Invalid response from Discogs: {response.text}")

    logger.info("✅ Discogs OAuth access token obtained")
    return {
        "oauth_token": params["oauth_token"],
        "oauth_token_secret": params["oauth_token_secret"],
    }


async def fetch_discogs_identity(
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    user_agent: str,
) -> dict[str, Any]:
    """Fetch the authenticated user's Discogs identity.

    Returns:
        dict with 'id', 'username', 'resource_url', etc.

    Raises:
        DiscogsOAuthError: if the request fails
    """
    nonce = os.urandom(16).hex()
    timestamp = str(int(time.time()))
    url = DISCOGS_IDENTITY_URL

    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    signature = _hmac_sha1_signature("GET", url, oauth_params, consumer_secret, access_token_secret)
    oauth_params["oauth_signature"] = signature

    headers = {
        "Authorization": _build_oauth_header(oauth_params),
        "User-Agent": user_agent,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        logger.debug("Discogs API error body", status=response.status_code, body=response.text)
        raise DiscogsOAuthError(f"Failed to fetch Discogs identity: HTTP {response.status_code}")

    identity: dict[str, Any] = response.json()
    logger.info("✅ Discogs identity fetched", username=identity.get("username"))
    return identity
