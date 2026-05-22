from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="ambiguous_request",
    prompt="give me a deal",
    assertions=[assert_called_tool("compute_bundles")],
)
