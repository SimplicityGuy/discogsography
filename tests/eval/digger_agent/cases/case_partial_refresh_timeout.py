from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="partial_refresh_timeout",
    prompt="Use the freshest data but I am in a hurry — do not wait long.",
    assertions=[assert_called_tool("compute_bundles")],
)
