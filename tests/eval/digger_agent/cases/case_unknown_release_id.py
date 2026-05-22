from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="unknown_release_id",
    prompt="Show me the current listings for release 999999999.",
    assertions=[assert_called_tool("get_listings_for_release")],
)
