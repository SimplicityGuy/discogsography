from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="what_if_no_budget",
    prompt="What if I had unlimited budget? Show me the best possible bundle.",
    assertions=[assert_called_tool("compute_bundles")],
)
