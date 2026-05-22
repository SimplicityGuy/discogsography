from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


# On a warmed session the second turn should hit prompt cache (cache_read > 0);
# verified at the usage level during live runs. Behaviorally, still recommends.
CASE = EvalCase(
    name="cache_warm_second_turn",
    prompt="Find me deals again with the same constraints.",
    assertions=[assert_called_tool("compute_bundles")],
)
