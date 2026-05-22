from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="multi_tool_chain",
    prompt="Summarize my marketplace coverage, then find the best bundle.",
    assertions=[assert_called_tool("summarize_marketplace_coverage"), assert_called_tool("compute_bundles")],
)
