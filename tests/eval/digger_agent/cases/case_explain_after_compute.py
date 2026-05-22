from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="explain_after_compute",
    prompt="Find the cheapest bundle and explain why it is the cheapest.",
    assertions=[assert_called_tool("compute_bundles"), assert_called_tool("explain_bundle")],
)
