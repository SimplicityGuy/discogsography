"""Discogs OAuth 1.0a signing helpers owned by the catalog API."""

from base64 import b64encode
import hashlib
import hmac
import urllib.parse


def _oauth_escape(value: str) -> str:
    """Percent-encode a value according to OAuth 1.0a rules."""
    return urllib.parse.quote(value, safe="")


def _hmac_sha1_signature(
    method: str,
    url: str,
    oauth_params: dict[str, str],
    consumer_secret: str,
    token_secret: str = "",  # nosec B107 -- OAuth request-token signing has no token secret yet
) -> str:
    """Create an OAuth 1.0a HMAC-SHA1 signature."""
    parameter_string = "&".join(f"{_oauth_escape(key)}={_oauth_escape(value)}" for key, value in sorted(oauth_params.items()))
    signature_base = "&".join((_oauth_escape(method.upper()), _oauth_escape(url), _oauth_escape(parameter_string)))
    signing_key = f"{_oauth_escape(consumer_secret)}&{_oauth_escape(token_secret)}"
    digest = hmac.HMAC(signing_key.encode("utf-8"), signature_base.encode("utf-8"), hashlib.sha1).digest()
    return b64encode(digest).decode("ascii")


def _build_oauth_header(params: dict[str, str]) -> str:
    """Build an OAuth Authorization header from OAuth protocol parameters."""
    values = ", ".join(f'{key}="{_oauth_escape(value)}"' for key, value in sorted(params.items()))
    return f"OAuth {values}"
