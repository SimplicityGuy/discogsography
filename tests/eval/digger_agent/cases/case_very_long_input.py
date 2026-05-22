from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


_PADDING = "I really care about pressing quality and original copies. " * 60
CASE = EvalCase(
    name="very_long_input",
    prompt=("Find me deals. " + _PADDING)[:3990],
    assertions=[assert_called_tool("compute_bundles")],
)
