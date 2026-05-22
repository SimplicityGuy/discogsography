"""Runs every CASE against the live Digger agent.

Gated: requires ``ANTHROPIC_API_KEY`` (and, via the ``agent_eval_harness``
fixture, a live stack). Skipped in regular CI — intended for nightly / manual
runs. The harness logic and the case library are unit-tested without a key in
``test_eval_cases.py``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from tests.eval.digger_agent.cases import ALL_CASES


if TYPE_CHECKING:
    from tests.eval.digger_agent.harness import EvalCase


@pytest.mark.eval
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY + a live stack")
@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.name)
@pytest.mark.asyncio
async def test_eval_case(case: EvalCase, agent_eval_harness) -> None:
    if case.setup is not None:
        await case.setup(agent_eval_harness.ctx.pool, agent_eval_harness.ctx.user_id)
    events = await agent_eval_harness.run(case)
    failures = [desc for desc, predicate in case.assertions if not predicate(events)]
    assert not failures, f"{case.name} failing assertions: {failures}"
