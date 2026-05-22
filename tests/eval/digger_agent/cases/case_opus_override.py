from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="opus_override",
    prompt="Find me deals.",
    model_override="opus",
    assertions=[assert_called_tool("compute_bundles")],
)
