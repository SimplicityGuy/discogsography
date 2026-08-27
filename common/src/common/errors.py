"""Exception-description helpers for diagnosable error logging.

Several exception types raised by the networking and database stacks carry an
**empty** ``str()`` — most notably ``httpx.ReadTimeout`` / ``httpx.ConnectTimeout``
/ ``httpx.ConnectError``, which are constructed with no message when the failure
comes from the transport layer. Logging ``error=str(exc)`` for those produces a
literal ``error=""`` line, which makes the failure unrecoverable from production
logs (observed for four ``community_enrichment`` failures, 2026-06-26 → 2026-07-19).

:func:`describe_exception` is the single helper every error log site should use
instead of ``str(exc)``: it always names the exception type, so the failure mode
is identifiable even when the message is empty.
"""

__all__ = ["describe_exception"]


def describe_exception(exc: BaseException) -> str:
    """Return a non-empty, diagnosable description of ``exc``.

    Always prefixes the exception's class name so a message-less exception (e.g.
    ``httpx.ReadTimeout``) still yields an identifiable log value.

    Args:
        exc: The exception to describe.

    Returns:
        ``"TypeName: message"`` when the exception stringifies non-empty,
        otherwise just ``"TypeName"``.

    Examples:
        >>> describe_exception(ValueError("bad input"))
        'ValueError: bad input'
        >>> describe_exception(TimeoutError())
        'TimeoutError'
    """
    detail = str(exc)
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
