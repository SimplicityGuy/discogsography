from tests.eval.digger_agent.harness import EvalCase, assert_tool_input_present


CASE = EvalCase(
    name="exclude_us_only",
    prompt="Only buy from sellers in the US — exclude everyone else.",
    assertions=[assert_tool_input_present("compute_bundles", "excluded_sellers")],
)
