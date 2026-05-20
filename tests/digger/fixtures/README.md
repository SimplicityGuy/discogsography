# Test Fixtures for Digger Parser Tests

## IMPORTANT: These fixtures are SYNTHETIC

All HTML files in this directory are **hand-authored** to match the documented
Discogs DOM structure as of **2026-05**. They were **NOT captured from live
Discogs pages**.

### Why synthetic?

The Digger M1 build pipeline does not make outbound HTTP requests to Discogs.
Fixtures exercise parser logic (CSS selector traversal, condition normalization,
price parsing, bleach sanitization) against a controlled, stable DOM shape. They
cannot prove that the selectors work against the real Discogs site, which may
change its HTML structure at any time.

### Deferred verification

Verifying these selectors against live Discogs HTML is explicitly deferred to:

- **Task 28 — M1 e2e smoke test** (`tests/e2e/test_digger_m1_smoke.py`) which
  fetches real pages in a controlled test environment.
- **Manual QA** before the feature ships to production.

---

## Fixture inventory

### `listing_page_basic.html`

**Purpose:** Exercises `digger/scraper/listing_parser.py`

**Rows included:**

| listing_id | Condition (media) | Price | Notes |
|------------|-------------------|-------|-------|
| 20001 | NM | USD 12.99 | Comment contains `<b>` tag — bleach sanitization test |
| 20002 | `(NM or better)` | EUR 8.50 | Condition normalization — "or better" form |
| 20003 | VG+ | GBP 6.00 | No comment field |

**Tests exercised:**
- At least 2 listings extracted
- `listing_id=20002` normalizes to `NM`
- `listing_id=20001` comment has `<b>` stripped by bleach, leaving plain text
- Empty `div.no-results` returns `[]`
- Plain "No listings available" text returns `[]`
- Garbage HTML missing `table#pjax_container` raises `UnknownLayoutError`

**sha256:** `746afef0b677b40acc647a58bd65c971b5c76a4150f309048aa2803f55e913b7`

**Authored:** 2026-05-19

---

### `seller_page_basic.html`

**Purpose:** Exercises `digger/scraper/seller_parser.py`

**Contents:**

- `seller_id`: 54321 (embedded in `/users/54321` href)
- `username`: VinylKingRecords
- `country`: United States → `US`
- `feedback_count`: 1523, `feedback_score`: 99.7
- Shipping policy: 3 regions (us, europe, worldwide)

**Tests exercised:**
- `seller_id` and `username` extracted correctly
- `country_code == "US"` from "United States" mapping
- `shipping_policy` contains at least 1 region with `first_cents` and
  `additional_cents`
- `ships_internationally == True` (derived from non-empty policy)
- Page with no `/users/` link raises `ValueError("seller link missing")`

**sha256:** `e2ddc8e5c1794abc776421e596f102a66ff371f047ccff5a760e1fccf55bd883`

**Authored:** 2026-05-19
