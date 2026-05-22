from tests.eval.digger_agent.harness import EvalCase, assert_no_fabricated_numbers


# Exercised end-to-end through the SSE endpoint (which returns 429 once the daily
# interactive token cap is exhausted); within the agent loop we assert the model
# does not fabricate figures.
CASE = EvalCase(
    name="token_cap_exceeded",
    prompt="Find me deals.",
    assertions=[assert_no_fabricated_numbers()],
)
