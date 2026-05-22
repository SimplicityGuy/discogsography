from tests.eval.digger_agent.harness import EvalCase, assert_called_tool


CASE = EvalCase(
    name="save_with_title",
    prompt='Find good deals and save them as a report titled "Q1 hunt".',
    assertions=[assert_called_tool("compute_bundles"), assert_called_tool("save_report")],
)
