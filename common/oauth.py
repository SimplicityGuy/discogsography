"""OAuth 1.0a utility functions shared across services."""

from base64 import b64encode
import hashlib
import hmac
import urllib.parse


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
    param_string = "&".join(f"{_oauth_escape(k)}={_oauth_escape(v)}" for k, v in sorted(oauth_params.items()))
    base_string = "&".join(
        [
            _oauth_escape(method.upper()),
            _oauth_escape(url),
            _oauth_escape(param_string),
        ]
    )
    signing_key = f"{_oauth_escape(consumer_secret)}&{_oauth_escape(token_secret)}"
    digest = hmac.HMAC(signing_key.encode("ascii"), base_string.encode("ascii"), hashlib.sha1).digest()
    return b64encode(digest).decode("ascii")
