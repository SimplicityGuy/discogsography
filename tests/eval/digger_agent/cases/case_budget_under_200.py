from tests.eval.digger_agent.harness import EvalCase, assert_tool_input_equals


CASE = EvalCase(
    name="budget_under_200",
    prompt="I have $200 to spend — find me the best deal.",
    assertions=[assert_tool_input_equals("compute_bundles", "budget_cap_cents", 20000)],
)
