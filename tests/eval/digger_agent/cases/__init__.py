"""Eval case library — one CASE per module, aggregated into ``ALL_CASES``.

Imports are explicit (rather than dynamic discovery) so the set of cases is
statically analyzable and the runner needs no dynamic ``import_module``.
"""

from tests.eval.digger_agent.cases.case_ambiguous_request import CASE as ambiguous_request
from tests.eval.digger_agent.cases.case_basic_recommend import CASE as basic_recommend
from tests.eval.digger_agent.cases.case_budget_under_200 import CASE as budget_under_200
from tests.eval.digger_agent.cases.case_cache_warm_second_turn import CASE as cache_warm_second_turn
from tests.eval.digger_agent.cases.case_concurrency_lock import CASE as concurrency_lock
from tests.eval.digger_agent.cases.case_empty_wantlist import CASE as empty_wantlist
from tests.eval.digger_agent.cases.case_exclude_us_only import CASE as exclude_us_only
from tests.eval.digger_agent.cases.case_explain_after_compute import CASE as explain_after_compute
from tests.eval.digger_agent.cases.case_listing_with_injected_prompt import CASE as listing_with_injected_prompt
from tests.eval.digger_agent.cases.case_multi_tool_chain import CASE as multi_tool_chain
from tests.eval.digger_agent.cases.case_opus_override import CASE as opus_override
from tests.eval.digger_agent.cases.case_partial_refresh_timeout import CASE as partial_refresh_timeout
from tests.eval.digger_agent.cases.case_propose_tier_changes import CASE as propose_tier_changes
from tests.eval.digger_agent.cases.case_refresh_before_compute import CASE as refresh_before_compute
from tests.eval.digger_agent.cases.case_save_with_title import CASE as save_with_title
from tests.eval.digger_agent.cases.case_token_cap_exceeded import CASE as token_cap_exceeded
from tests.eval.digger_agent.cases.case_tool_input_validation import CASE as tool_input_validation
from tests.eval.digger_agent.cases.case_unknown_release_id import CASE as unknown_release_id
from tests.eval.digger_agent.cases.case_very_long_input import CASE as very_long_input
from tests.eval.digger_agent.cases.case_what_if_no_budget import CASE as what_if_no_budget


ALL_CASES = (
    ambiguous_request,
    basic_recommend,
    budget_under_200,
    cache_warm_second_turn,
    concurrency_lock,
    empty_wantlist,
    exclude_us_only,
    explain_after_compute,
    listing_with_injected_prompt,
    multi_tool_chain,
    opus_override,
    partial_refresh_timeout,
    propose_tier_changes,
    refresh_before_compute,
    save_with_title,
    token_cap_exceeded,
    tool_input_validation,
    unknown_release_id,
    very_long_input,
    what_if_no_budget,
)
