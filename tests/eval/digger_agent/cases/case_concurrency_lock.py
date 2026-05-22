from tests.eval.digger_agent.harness import EvalCase, assert_no_fabricated_numbers


# Exercised end-to-end through the SSE endpoint (a second concurrent turn yields
# an error event); within the agent loop we assert sane behavior.
CASE = EvalCase(
    name="concurrency_lock",
    prompt="Find me deals.",
    assertions=[assert_no_fabricated_numbers()],
)
