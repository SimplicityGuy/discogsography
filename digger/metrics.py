"""Prometheus metrics registered once at import time."""

from prometheus_client import Counter, Gauge


SCRAPE_TOTAL = Counter(
    "digger_scrape_total",
    "Total scrape attempts by outcome",
    labelnames=("outcome",),
)
RATE_BUDGET_REMAINING = Gauge(
    "digger_rate_budget_remaining",
    "Tokens remaining in the rate budget bucket",
)
QUEUE_DEPTH = Gauge(
    "digger_queue_depth",
    "Releases due for scraping",
    labelnames=("tier",),
)
UNKNOWN_LAYOUT_TOTAL = Counter(
    "digger_unknown_layout_total",
    "Pages where the parser found an unexpected layout",
)
CIRCUIT_BREAKER_OPEN = Gauge(
    "digger_circuit_breaker_open",
    "1 if circuit breaker is open, else 0",
)
