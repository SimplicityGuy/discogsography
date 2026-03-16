"""Tests for rate limiter singleton."""

from api.limiter import limiter


class TestLimiter:
    def test_limiter_is_importable(self) -> None:
        assert limiter is not None

    def test_limiter_has_key_func(self) -> None:
        assert limiter._key_func is not None

    def test_limiter_is_singleton(self) -> None:
        from api.limiter import limiter as limiter2

        assert limiter is limiter2
