from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="basic_recommend",
    prompt="Find me some good deals from my wantlist.",
    assertions=[assert_called_tool("compute_bundles")],
)
