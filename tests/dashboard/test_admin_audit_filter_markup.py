"""Regression test for discogsography-zjg7.

Pins dashboard/static/admin.html's audit-log action-filter `<select>` to being
well-formed markup. The opening tag was previously missing its closing '>',
which the HTML tokenizer parses as bogus attributes on the `<select>` (rather
than a nested `<option>`), silently dropping the `value=""` ("All Actions")
option and leaving `admin.login` as the default-selected value — hiding
logout/extraction/dlq-purge audit events with no UI control to reset the
filter.
"""

from html.parser import HTMLParser
from pathlib import Path


_ADMIN_HTML = Path(__file__).resolve().parents[2] / "dashboard" / "static" / "admin.html"


class _SelectOptionCollector(HTMLParser):
    """Collects the real (well-formed-HTML) child <option> values of a given <select> id."""

    def __init__(self, select_id: str) -> None:
        super().__init__()
        self.select_id = select_id
        self.in_target_select = False
        self.depth = 0
        self.option_values: list[str] = []
        self._select_attrs: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "select" and attrs_dict.get("id") == self.select_id:
            self.in_target_select = True
            self.depth = 1
            self._select_attrs = attrs_dict
            return
        if self.in_target_select:
            if tag == "select":
                self.depth += 1
            elif tag == "option":
                self.option_values.append(attrs_dict.get("value") or "")

    def handle_endtag(self, tag: str) -> None:
        if self.in_target_select and tag == "select":
            self.depth -= 1
            if self.depth == 0:
                self.in_target_select = False


def _collect_options(select_id: str) -> _SelectOptionCollector:
    parser = _SelectOptionCollector(select_id)
    parser.feed(_ADMIN_HTML.read_text())
    return parser


def test_audit_log_action_filter_select_has_closing_bracket() -> None:
    """The <select> opening tag must be closed with '>' (not a bogus-attribute state)."""
    content = _ADMIN_HTML.read_text()
    idx = content.index('<select id="al-action-filter"')
    # The next '<' after the opening tag's start must belong to a real nested
    # element (i.e. the tag closed with '>' before any other '<').
    close_bracket_idx = content.index(">", idx)
    next_open_bracket_idx = content.index("<", idx + 1)
    assert close_bracket_idx < next_open_bracket_idx, (
        "The <select id=\"al-action-filter\"> opening tag is not closed before the next '<' — "
        "a dropped '>' causes the HTML tokenizer to consume the following <option> as bogus "
        "attributes of <select>, destroying the 'All Actions' option (discogsography-zjg7)."
    )


def test_audit_log_action_filter_has_all_actions_option() -> None:
    """The filter must have a real, default-selected value='' ('All Actions') option."""
    collector = _collect_options("al-action-filter")
    assert collector.option_values, "No <option> children were parsed under #al-action-filter"
    assert collector.option_values[0] == "", (
        f"Expected the first option's value to be '' (All Actions, and thus the default-"
        f"selected value), got {collector.option_values[0]!r}. Got options: {collector.option_values!r}"
    )


def test_audit_log_action_filter_has_all_four_named_actions() -> None:
    """All four named audit actions must still be present alongside the 'All Actions' option."""
    collector = _collect_options("al-action-filter")
    assert collector.option_values == [
        "",
        "admin.login",
        "admin.logout",
        "extraction.trigger",
        "dlq.purge",
    ]
