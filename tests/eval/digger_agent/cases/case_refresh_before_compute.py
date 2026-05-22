from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="refresh_before_compute",
    prompt="Use the freshest listings available, then recommend a bundle.",
    assertions=[assert_called_tool("request_opportunistic_refresh"), assert_called_tool("compute_bundles")],
)
