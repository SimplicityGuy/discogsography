"""Tests for rate limiter singleton."""

import warnings

from fastapi import Request

from api.limiter import limiter


class TestLimiter:
    def test_limiter_is_importable(self) -> None:
        assert limiter is not None

    def test_limiter_has_key_func(self) -> None:
        assert limiter._key_func is not None

    def test_limiter_is_singleton(self) -> None:
        from api.limiter import limiter as limiter2

        assert limiter is limiter2

    def test_limit_decorator_avoids_asyncio_coroutine_deprecation(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)

            @limiter.limit("1/minute")
            async def endpoint(request: Request) -> None:
                pass

        assert endpoint is not None

    def test_exempt_decorator_avoids_asyncio_coroutine_deprecation(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)

            @limiter.exempt
            async def endpoint(request: Request) -> None:
                pass

        assert endpoint is not None
