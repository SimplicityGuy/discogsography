from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="propose_tier_changes",
    prompt="These records keep getting fresh listings — bump my top three to Must.",
    assertions=[assert_called_tool("propose_tier_changes")],
)
