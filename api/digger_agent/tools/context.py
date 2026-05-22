"""Shared execution context passed to every digger agent tool.

Lives in its own module (not ``dispatch.py``) so the per-tool modules can import
``ToolContext`` without a circular import back to the dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:  # pragma: no cover
    import uuid

    from redis.asyncio import Redis

    from common import AsyncPostgreSQLPool
    from common.digger_optimizer.models import OptimizerOutput


@dataclass(slots=True)
class ToolContext:
    """Per-turn state threaded through tool dispatch.

    ``last_optimizer_output`` lets ``explain_bundle`` and ``save_report`` reuse the
    most recent ``compute_bundles`` result without re-running the optimizer.
    """

    pool: AsyncPostgreSQLPool
    redis: Redis | None
    user_id: uuid.UUID
    session_id: uuid.UUID | None = None
    last_optimizer_output: OptimizerOutput | None = None
