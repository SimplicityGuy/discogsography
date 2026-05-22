from tests.eval.digger_agent.harness import EvalCase, assert_no_fabricated_numbers


CASE = EvalCase(
    name="tool_input_validation",
    prompt='Show me listings for release "not-a-number".',
    assertions=[assert_no_fabricated_numbers()],
)
