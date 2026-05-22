from tests.eval.digger_agent.harness import EvalCase, assert_no_fabricated_numbers, assert_not_called_tool


CASE = EvalCase(
    name="empty_wantlist",
    prompt="Find me deals.",
    assertions=[assert_not_called_tool("compute_bundles"), assert_no_fabricated_numbers()],
)
