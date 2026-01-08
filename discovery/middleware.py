"""Middleware for request tracking and correlation."""

import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from discovery.metrics import active_requests, error_count, request_count, request_duration


logger = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add unique request ID to each request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add request ID.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response with request ID header
        """
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Store request ID in request state for access by handlers
        request.state.request_id = request_id

        # Bind request ID to logger context
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # Extract endpoint path and method for metrics
        method = request.method
        endpoint = request.url.path

        # Increment active requests gauge
        active_requests.labels(method=method, endpoint=endpoint).inc()

        # Record start time
        start_time = time.time()

        try:
            # Process request
            response = await call_next(request)

            # Calculate processing time
            process_time = time.time() - start_time

            # Record metrics
            request_count.labels(
                method=method,
                endpoint=endpoint,
                status_code=response.status_code,
            ).inc()

            request_duration.labels(
                method=method,
                endpoint=endpoint,
            ).observe(process_time)

            # Add request ID and processing time to response headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.4f}"

            # Log request completion
            logger.info(
                "✅ Request completed",
                status_code=response.status_code,
                process_time=f"{process_time:.4f}s",
            )

            return response

        except Exception as e:
            # Calculate processing time for failed request
            process_time = time.time() - start_time

            # Record error metrics
            error_count.labels(
                method=method,
                endpoint=endpoint,
                error_type=type(e).__name__,
            ).inc()

            request_count.labels(
                method=method,
                endpoint=endpoint,
                status_code=500,
            ).inc()

            # Log error with request context
            logger.error(
                "❌ Request failed",
                error=str(e),
                error_type=type(e).__name__,
                process_time=f"{process_time:.4f}s",
            )

            raise

        finally:
            # Decrement active requests gauge
            active_requests.labels(method=method, endpoint=endpoint).dec()

            # Clear context variables for next request
            structlog.contextvars.clear_contextvars()


def get_request_id(request: Request) -> str:
    """Get request ID from request state.

    Args:
        request: Current request

    Returns:
        Request ID string
    """
    return getattr(request.state, "request_id", "unknown")
