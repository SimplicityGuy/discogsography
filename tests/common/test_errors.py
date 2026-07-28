"""Tests for common.errors.describe_exception."""

import httpx
import pytest

from common import describe_exception
from common.errors import describe_exception as direct_describe_exception


class TestDescribeException:
    """describe_exception must never return an empty string."""

    def test_exception_with_message_includes_type_and_message(self) -> None:
        assert describe_exception(ValueError("bad input")) == "ValueError: bad input"

    def test_exception_without_message_falls_back_to_type_name(self) -> None:
        assert describe_exception(TimeoutError()) == "TimeoutError"

    def test_read_timeout_names_the_type(self) -> None:
        """The regression that motivated this helper: httpx.ReadTimeout str() is empty."""
        exc = httpx.ReadTimeout("")
        assert str(exc) == ""  # guards the premise of the bug
        assert describe_exception(exc) == "ReadTimeout"
        assert "ReadTimeout" in describe_exception(exc)

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout(""),
            httpx.ConnectTimeout(""),
            httpx.ConnectError(""),
            httpx.PoolTimeout(""),
            httpx.WriteTimeout(""),
        ],
    )
    def test_message_less_httpx_transport_errors_are_diagnosable(self, exc: Exception) -> None:
        described = describe_exception(exc)
        assert described != ""
        assert described == type(exc).__name__

    def test_never_returns_empty_for_a_bare_exception(self) -> None:
        assert describe_exception(Exception()) == "Exception"

    def test_accepts_base_exception(self) -> None:
        assert describe_exception(KeyboardInterrupt()) == "KeyboardInterrupt"

    def test_reexported_from_common_package(self) -> None:
        assert describe_exception is direct_describe_exception
