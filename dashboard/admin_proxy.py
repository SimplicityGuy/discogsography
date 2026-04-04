"""Proxy router for admin API calls to the API service.

All proxied requests target a fixed internal API base URL configured via
server-side environment variables only.  Path parameters are validated
with strict alphanumeric patterns to prevent path-traversal.  Request
bodies are validated as JSON and re-serialised before forwarding.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Query, Request, Response
import httpx
from starlette.responses import JSONResponse
import structlog


logger = structlog.get_logger(__name__)

router = APIRouter()

# Fixed internal API base URL — set once at startup from env vars, never
# from user input.  This is NOT an SSRF vector because callers cannot
# influence the destination host or port.
_api_base_url: str = "http://api:8004"

# Strict pattern for path parameters forwarded to the API.
# Dots are allowed to support version strings like "20240101.0".
_SAFE_PATH_SEGMENT = re.compile(r"^[a-zA-Z0-9._-]+$")


def configure(api_host: str, api_port: int) -> None:
    """Set API service connection details (called once at startup)."""
    global _api_base_url
    _api_base_url = f"http://{api_host}:{api_port}"


def _validate_path_segment(value: str) -> bool:
    """Return True when *value* is safe to embed in a URL path."""
    return bool(_SAFE_PATH_SEGMENT.match(value))


def _auth_headers(request: Request) -> dict[str, str]:
    """Extract Authorization header from the incoming request."""
    headers: dict[str, str] = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth
    return headers


def _unavailable_response() -> Response:
    return Response(content=b'{"detail":"API service unavailable"}', status_code=502, media_type="application/json")


def _ok_response(resp: httpx.Response) -> Response:
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


def _build_url(api_path: str) -> str:
    """Build a full URL from the fixed base and a hardcoded API path.

    This is only called with string literals defined in this module —
    never with user-supplied data.
    """
    return f"{_api_base_url}{api_path}"


async def _validated_json_body(request: Request) -> bytes | None:
    """Read the request body, validate it as JSON, and re-serialise.

    Re-serialising through ``json.loads`` / ``json.dumps`` sanitises the
    payload so that no raw user bytes are forwarded verbatim.  Returns
    ``None`` when the body is empty.
    """
    raw = await request.body()
    if not raw:
        return None
    parsed = json.loads(raw)
    return json.dumps(parsed, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# Routes — each maps a dashboard path to a fixed API path.
# Every handler builds its own URL from a hardcoded literal path.
# ---------------------------------------------------------------------------


@router.post("/admin/api/login")
async def proxy_login(request: Request) -> Response:
    """Proxy login requests to the API service."""
    url = _build_url("/api/admin/auth/login")
    headers = _auth_headers(request)
    try:
        sanitised_body = await _validated_json_body(request)
    except json.JSONDecodeError:
        return JSONResponse(content={"detail": "Malformed JSON in request body"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if sanitised_body:
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, headers=headers, content=sanitised_body)
            else:
                resp = await client.post(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.post("/admin/api/logout")
async def proxy_logout(request: Request) -> Response:
    """Proxy logout requests to the API service."""
    url = _build_url("/api/admin/auth/logout")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extractions")
async def proxy_list_extractions(request: Request) -> Response:
    """Proxy extraction list requests to the API service."""
    url = _build_url("/api/admin/extractions")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extractions/{extraction_id}")
async def proxy_get_extraction(extraction_id: str, request: Request) -> Response:
    """Proxy extraction detail requests to the API service."""
    if not _validate_path_segment(extraction_id):
        return Response(content=b'{"detail":"Invalid extraction ID"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extractions/{extraction_id}")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.post("/admin/api/extractions/trigger")
async def proxy_trigger(request: Request) -> Response:
    """Proxy extraction trigger requests to the API service."""
    url = _build_url("/api/admin/extractions/trigger")
    headers = _auth_headers(request)
    try:
        sanitised_body = await _validated_json_body(request)
    except json.JSONDecodeError:
        return JSONResponse(content={"detail": "Malformed JSON in request body"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if sanitised_body:
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, headers=headers, content=sanitised_body)
            else:
                resp = await client.post(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.post("/admin/api/extractions/trigger-musicbrainz")
async def proxy_trigger_musicbrainz(request: Request) -> Response:
    """Proxy MusicBrainz extraction trigger requests to the API service."""
    url = _build_url("/api/admin/extractions/trigger")
    headers = _auth_headers(request)
    try:
        sanitised_body = await _validated_json_body(request)
    except json.JSONDecodeError:
        return JSONResponse(content={"detail": "Malformed JSON in request body"}, status_code=400)
    try:
        parsed = json.loads(sanitised_body) if sanitised_body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(content={"detail": "Malformed JSON in request body"}, status_code=400)
    if not isinstance(parsed, dict):
        return JSONResponse(content={"detail": "Request body must be a JSON object"}, status_code=400)
    body_dict: dict = parsed
    body_dict["source"] = "musicbrainz"
    payload = json.dumps(body_dict, separators=(",", ":")).encode()
    headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, content=payload)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


# ---------------------------------------------------------------------------
# Phase 2 — User Activity & Storage proxy routes
# ---------------------------------------------------------------------------


@router.get("/admin/api/users/stats")
async def proxy_user_stats(request: Request) -> Response:
    """Proxy user stats requests to the API service."""
    url = _build_url("/api/admin/users/stats")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/users/sync-activity")
async def proxy_sync_activity(request: Request) -> Response:
    """Proxy sync activity requests to the API service."""
    url = _build_url("/api/admin/users/sync-activity")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/storage")
async def proxy_storage(request: Request) -> Response:
    """Proxy storage utilization requests to the API service."""
    url = _build_url("/api/admin/storage")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.post("/admin/api/dlq/purge/{queue}")
async def proxy_dlq_purge(queue: str, request: Request) -> Response:
    """Proxy DLQ purge requests to the API service."""
    if not _validate_path_segment(queue):
        return Response(content=b'{"detail":"Invalid queue name"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/dlq/purge/{queue}")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


# ---------------------------------------------------------------------------
# Phase 3 — Queue Health Trends & System Health proxy routes
# ---------------------------------------------------------------------------


@router.get("/admin/api/queues/history")
async def proxy_queue_history(
    request: Request,
    range: str | None = Query(default=None, pattern=r"^[0-9]+[hdwm]$"),
    granularity: str | None = Query(default=None, pattern=r"^[0-9]+(min|hour|day)$"),
) -> Response:
    """Proxy queue history requests to the API service."""
    url = _build_url("/api/admin/queues/history")
    params: dict[str, str] = {}
    if range is not None:
        params["range"] = range
    if granularity is not None:
        params["granularity"] = granularity
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/health/history")
async def proxy_health_history(
    request: Request,
    range: str | None = Query(default=None, pattern=r"^[0-9]+[hdwm]$"),
    granularity: str | None = Query(default=None, pattern=r"^[0-9]+(min|hour|day)$"),
) -> Response:
    """Proxy health history requests to the API service."""
    url = _build_url("/api/admin/health/history")
    params: dict[str, str] = {}
    if range is not None:
        params["range"] = range
    if granularity is not None:
        params["granularity"] = granularity
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


# ---------------------------------------------------------------------------
# Phase 4 — Audit Log proxy route
# ---------------------------------------------------------------------------


@router.get("/admin/api/audit-log")
async def proxy_audit_log(
    request: Request,
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=100),
    action: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_.]+$"),
    admin_id: str | None = Query(default=None, pattern=r"^[a-f0-9-]+$"),
) -> Response:
    """Proxy audit log requests to the API service."""
    url = _build_url("/api/admin/audit-log")
    params: dict[str, str] = {}
    if page is not None:
        params["page"] = str(page)
    if page_size is not None:
        params["page_size"] = str(page_size)
    if action is not None:
        params["action"] = action
    if admin_id is not None:
        params["admin_id"] = admin_id
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


# ---------------------------------------------------------------------------
# Phase 5 — Extraction Analysis proxy routes
# ---------------------------------------------------------------------------


@router.get("/admin/api/extraction-analysis/versions")
async def proxy_ea_versions(request: Request) -> Response:
    """Proxy extraction analysis versions list to the API service."""
    url = _build_url("/api/admin/extraction-analysis/versions")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/summary")
async def proxy_ea_summary(version: str, request: Request) -> Response:
    """Proxy extraction analysis summary for a single version."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/summary")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/violations/{record_id}")
async def proxy_ea_violation_detail(version: str, record_id: str, request: Request) -> Response:
    """Proxy extraction analysis violation record detail — must be registered before the bare violations route."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    if not _validate_path_segment(record_id):
        return Response(content=b'{"detail":"Invalid record ID"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/violations/{record_id}")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/violations")
async def proxy_ea_violations(
    version: str,
    request: Request,
    entity_type: str | None = Query(default=None, pattern=r"^[a-z-]+$"),
    severity: str | None = Query(default=None, pattern=r"^(error|warning|info)$"),
    rule: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9_-]+$"),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
) -> Response:
    """Proxy extraction analysis violations list with optional query param filtering."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/violations")
    params: dict[str, str] = {}
    if entity_type is not None:
        params["entity_type"] = entity_type
    if severity is not None:
        params["severity"] = severity
    if rule is not None:
        params["rule"] = rule
    if page is not None:
        params["page"] = str(page)
    if page_size is not None:
        params["page_size"] = str(page_size)
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/parsing-errors")
async def proxy_ea_parsing_errors(version: str, request: Request) -> Response:
    """Proxy extraction analysis parsing errors — uses longer timeout as parsing can be slow."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/parsing-errors")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.get("/admin/api/extraction-analysis/{version}/compare/{other_version}")
async def proxy_ea_compare(version: str, other_version: str, request: Request) -> Response:
    """Proxy extraction analysis version comparison."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    if not _validate_path_segment(other_version):
        return Response(content=b'{"detail":"Invalid other_version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/compare/{other_version}")
    headers = _auth_headers(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)


@router.post("/admin/api/extraction-analysis/{version}/prompt-context")
async def proxy_ea_prompt_context(version: str, request: Request) -> Response:
    """Proxy extraction analysis prompt context generation."""
    if not _validate_path_segment(version):
        return Response(content=b'{"detail":"Invalid version"}', status_code=400, media_type="application/json")
    url = _build_url(f"/api/admin/extraction-analysis/{version}/prompt-context")
    headers = _auth_headers(request)
    try:
        sanitised_body = await _validated_json_body(request)
    except json.JSONDecodeError:
        return JSONResponse(content={"detail": "Malformed JSON in request body"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if sanitised_body:
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, headers=headers, content=sanitised_body)
            else:
                resp = await client.post(url, headers=headers)
    except (httpx.ConnectError, httpx.RequestError) as exc:
        logger.error("❌ API service unreachable", url=url, error=str(exc))
        return _unavailable_response()
    return _ok_response(resp)
