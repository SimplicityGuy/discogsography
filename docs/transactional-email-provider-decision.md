# Decision Record: Transactional Email Provider (Brevo Replacement)

**Status:** Accepted
**Date:** 2026-08-03
**Bead:** `discogsography-eef5` (spike)
**Implements:** `discogsography-iew6` (remove Brevo, integrate the replacement)
**Decision:** Adopt **Resend** over plain REST (`httpx`). Runner-up: **Amazon SES** à la carte.

## Context

Brevo is being dropped. On its free tier, Brevo rewrites every outbound link to inject
click tracking, with no per-message way to turn it off — `api/notifications.py` already
carries a comment documenting that the v3 transactional API rejects the `X-Mailin-Track*`
headers and that tracking can only be disabled from the dashboard. Password reset URLs
arriving wrapped in a `sendibt2.com` redirect is unacceptable: the link must arrive
byte-identical to what the API service authored.

The service sends exactly one class of mail today — password reset links, one recipient
per message, triggered by user action. Volume is tens of messages per month, not
thousands.

### Hard requirements

1. **No forced link tracking.** Click tracking must be off, or disableable, on the tier we
   would actually use — not a paid-tier-only toggle (the exact trap Brevo set).
2. **Pricing shape.** Free, a genuinely usable free tier, or credit / pay-as-you-go.
   Explicitly **not** a recurring monthly subscription.
3. **Transactional email**, not marketing campaigns.

## Comparison

Requirement 1 is answered against the *qualifying* tier for each provider — the tier
requirement 2 would put us on.

| Provider | Req 1: link tracking off on our tier? | Req 2: pricing shape | Qualifying tier limits | Overage behavior |
|---|---|---|---|---|
| **Resend** | ✅ **Off by default, all domains.** "Open and click tracking is disabled by default for all domains." Tracking is not merely toggleable — enabling it requires standing up a tracking subdomain first. Not tier-gated. ([docs][r-track]) | ✅ Free tier | 3,000/mo, **100/day**, 1 domain ([pricing][r-price]) | Hard stop — no overage charge; you cannot exceed without upgrading |
| **Amazon SES** | ✅ **Structurally impossible unless opted in.** SES rewrites links only when a configuration set publishes `click` events: "When you use event publishing to capture open and click events, Amazon SES makes minor changes to the emails you send… To capture link click events, SES replaces the links." Send without such a configuration set → links untouched. ([docs][ses-track]) | ✅ À la carte PAYG, "no minimum fees" | $0.10 / 1,000 emails, no subscription ([pricing][ses-price]). Sandbox: 200/day, 1/sec, verified recipients only until production access is granted ([docs][ses-sandbox]) | Metered — charged per send, no cap |
| **Scaleway TEM** | ✅ **No click-tracking feature exists.** Nothing in the TEM docs offers it; the [feature request][scw-fr] filed 2022-12 is still open. Cannot rewrite what it cannot do. | ✅ Essential: PAYG, no subscription | 300/mo free per organization, then €0.25 / 1,000 ([pricing][scw-price]) | Metered. Sending capacity assessed case-by-case for new accounts |
| **Postmark** | ✅ `TrackLinks` defaults to `"None"` "for all messages and new and existing servers"; per-message override via API/`X-PM-TrackLinks` ([docs][pm-track], [API][pm-api]) | ❌ Free tier is 100/mo, then **$15/mo subscription** with no intermediate step ([pricing][pm-price]) | 100/mo on free | n/a |
| **MailerSend** | ✅ Per-domain **Track opens** / **Track clicks** toggles; email tracking is listed as a Free-plan feature ([docs][ms-track]) | ❌ Free 500/mo, then monthly subscription ([pricing][ms-price]) | 500/mo, 1 domain, 1 API token, 100 API requests/day | Paid plans charge per 1,000 over |
| **SMTP2GO** | ✅ Click tracking is enabled per SMTP user / IP / API key — not on by default ([docs][s2g-track]) | ❌ Free 1,000/mo, then subscription only ($10/mo Starter); no true PAYG ([pricing][s2g-price]) | 1,000/mo, 200/day, 25/hr until the sending domain is verified | Extra emails purchasable, but only inside a subscription |
| **Mailgun** | ✅ Tracking is toggleable (`o:tracking-clicks`) | ❌ **No standalone flex/PAYG plan.** Free is 100/day; everything above is a monthly subscription ([pricing][mg-price]) | 100/day on free | Overage billed inside a subscription |

**Requirement 1 is not the discriminator** — every candidate can send an unrewritten link
on its qualifying tier. Brevo is the outlier, not the norm. **Requirement 2 is what
decides it:** Postmark, MailerSend, SMTP2GO, and Mailgun all resolve to a recurring
monthly subscription the moment their thin free tier is outgrown, which is exactly the
shape the bead rules out. That leaves Resend, SES, and Scaleway TEM.

### Also-evaluated criteria

| | Resend | Amazon SES | Scaleway TEM |
|---|---|---|---|
| **Open-tracking pixel** | Off by default, same setting as clicks ([docs][r-track]) | Only via configuration set event publishing; supports an explicit `{{ses:openTracker}}` placeholder when you *do* want it ([docs][ses-track]) | Not offered |
| **Integration shape** | Single `POST https://api.resend.com/emails`, `Authorization: Bearer`, JSON body of `from`/`to`/`subject`/`html` ([API][r-api]) — trivial over `httpx`, no SDK needed | SigV4 request signing makes raw REST impractical → `boto3`/`aioboto3` is effectively mandatory | REST `POST` with `X-Auth-Token`; no SDK needed |
| **SDK risk** | Avoidable entirely — REST is 6 lines. Directly addresses the `brevo-python` 4→5 pain that motivated this spike | Adds `boto3` (large, but exceptionally stable API surface) | Avoidable entirely |
| **Setup burden** | Verify domain, add SPF/DKIM (and optionally DMARC) records | Verify domain identity, DKIM CNAMEs, **plus a production-access request** (24h initial response) and a bounce/complaint handling process, which AWS requires you to attest to ([docs][ses-sandbox]) | Verify domain, SPF/DKIM/DMARC |
| **Data residency (PII)** | Sending region selectable (e.g. `eu-west-1`), but **all account data, email metadata and logs are stored in the US** regardless; EU-US DPF certified, SCCs in place ([docs][r-region]) | Region of your choosing, including EU regions, for both sending and storage | EU (France), strongest residency story |

## Decision

**Adopt Resend**, called over plain REST with `httpx`.

Rationale:

- **Requirement 1 is satisfied by default, not by configuration.** Nothing has to be
  remembered, toggled, or re-checked after an account migration — the failure mode that
  bit us with Brevo requires an operator to have *deliberately* stood up a tracking
  subdomain. This is the strongest form of the guarantee among the plausible candidates.
- **The free tier genuinely covers the workload.** 3,000/mo and 100/day against a
  password-reset volume in the tens per month is two orders of magnitude of headroom, and
  it is free rather than a subscription. Overage is a hard stop, so there is no surprise
  bill.
- **It removes an SDK rather than swapping one.** The immediate cause of this spike was
  being pinned at `brevo-python>=4.0.10,<5` with no safe migration path. A four-field JSON
  POST over the `httpx` we already depend on has no major-version treadmill at all.
- **Setup burden is one domain verification.** No sandbox escape, no production-access
  review, no bounce-handling attestation before the first send.

**Runner-up: Amazon SES à la carte** ($0.10/1,000, no subscription, no minimum). Choose it
over Resend if either of these becomes true:

- **Free-tier risk matters more than setup cost.** Resend's free tier is a commercial
  decision Resend can revise; SES's metered rate is the product. At our volume SES costs
  well under a cent a month, so "pay-as-you-go" is effectively free *and* rug-pull-proof.
- **Volume grows past 100/day.** Resend's daily cap, not the monthly one, is the binding
  constraint; SES has no equivalent ceiling after production access.

Its costs today are real but front-loaded: `boto3` as a new dependency, a production-access
request before any mail reaches an unverified recipient, and a required bounce/complaint
process.

**Third: Scaleway TEM** — the pick if EU data residency for account PII becomes a hard
requirement. It is the only candidate storing data in the EU, and the only one where click
tracking is impossible rather than merely disabled. Rejected as the default because 300/mo
free with case-by-case capacity assessment for new accounts is a tighter and less
predictable envelope than Resend's, for a residency requirement we do not currently have.

**Rejected:**

- **Postmark** — excellent tracking defaults and deliverability reputation, but $15/mo
  with nothing between 100/mo and 10,000/mo. Fails requirement 2.
- **MailerSend** — 500/mo free is thin, and the 100 API-requests/day free-tier limit is an
  additional ceiling; paid tiers are subscriptions. Fails requirement 2.
- **SMTP2GO** — usable 1,000/mo free tier, but no pay-as-you-go path above it. Fails
  requirement 2.
- **Mailgun** — the "flex" PAYG plan referenced in the bead no longer exists as a
  standalone offering; pricing is subscription plus overage. Fails requirement 2.

## Integration shape

**Transport:** REST over `httpx`. **No vendor SDK** — drop `brevo-python>=4.0.10,<5` from
`pyproject.toml` without adding a replacement.

`api/notifications.py` keeps the `NotificationChannel` protocol and `LogNotificationChannel`
fallback unchanged; `BrevoNotificationChannel` is replaced by `ResendNotificationChannel`.
The existing `asyncio.to_thread` wrapper disappears — `httpx.AsyncClient` is natively async.

```
POST https://api.resend.com/emails
Authorization: Bearer <RESEND_API_KEY>
Content-Type: application/json

{"from": "Discogsography <noreply@discogsography.com>",
 "to": ["user@example.com"],
 "subject": "Reset your Discogsography password",
 "html": "…"}
```

No tracking field is sent or needed — the request body has no tracking parameter, because
the setting lives on the domain and is off.

**Config keys** (`common/config.py`, alongside the existing `brevo_*` fields they replace):

| Field | Env var | Secret? | Default |
|---|---|---|---|
| `resend_api_key` | `RESEND_API_KEY` | ✅ via `get_secret()` | `None` — unset falls back to `LogNotificationChannel`, matching today's behavior |
| `resend_sender_email` | `RESEND_SENDER_EMAIL` | — | `noreply@discogsography.com` |
| `resend_sender_name` | `RESEND_SENDER_NAME` | — | `Discogsography` |

`RESEND_API_KEY` is read through the existing `get_secret()` helper, so
`RESEND_API_KEY_FILE` works unchanged under the `_FILE` convention.

**Docker secret** (`docker-compose.prod.yml`): rename the `brevo_api_key` secret to
`resend_api_key`, file `./secrets/resend_api_key.txt`, mounted at
`/run/secrets/resend_api_key` and referenced as `RESEND_API_KEY_FILE`.

**Sending limits to document for operators:** 3,000/mo, 100/day, 1 verified domain.
Overage is a hard stop, not a charge — if the daily cap is hit, sends fail and
`api/notifications.py` logs the failure via its existing `logger.exception` path. Password
reset remains functional-but-degraded rather than silently broken.

**DNS:** SPF and DKIM records for `discogsography.com` per Resend's domain verification
flow; DMARC recommended. Comparable to Brevo's existing setup — no new burden.

**Files touched by the implementation bead:** `api/notifications.py`, `common/config.py`,
`pyproject.toml`, `docker-compose.yml`, `docker-compose.prod.yml`,
`tests/api/test_notifications.py`, `docs/configuration.md`, `docs/architecture.md`.

## Verification note

Claims above are cited to current vendor documentation, fetched 2026-08-03. Two carry a
caveat: Scaleway's capabilities and FAQ doc pages render client-side and returned only
navigation, so the "no click tracking" finding rests on the absence of the feature across
TEM's documented surface plus the still-open feature request — sufficient for a
third-choice ranking, but worth re-confirming with Scaleway support before adopting it.
SMTP2GO's support article returned HTTP 403 to automated fetch; its default-off behavior is
taken from the indexed summary of that article. Neither affects the recommendation.

[r-track]: https://resend.com/docs/dashboard/domains/tracking
[r-price]: https://resend.com/pricing
[r-api]: https://resend.com/docs/api-reference/emails/send-email
[r-region]: https://resend.com/docs/dashboard/domains/regions
[ses-track]: https://docs.aws.amazon.com/ses/latest/dg/configure-custom-open-click-domains.html
[ses-price]: https://aws.amazon.com/ses/pricing/
[ses-sandbox]: https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html
[scw-price]: https://www.scaleway.com/en/pricing/managed-services/
[scw-fr]: https://feature-request.scaleway.com/posts/528/click-tracking-on-transactional-emails
[pm-track]: https://postmarkapp.com/support/article/1058-how-do-i-enable-link-tracking
[pm-api]: https://postmarkapp.com/developer/api/email-api
[pm-price]: https://postmarkapp.com/pricing
[ms-track]: https://www.mailersend.com/help/domain-tracking-options
[ms-price]: https://www.mailersend.com/pricing
[s2g-track]: https://support.smtp2go.com/hc/en-gb/articles/900002237106-Click-Tracking
[s2g-price]: https://www.smtp2go.com/pricing/
[mg-price]: https://www.mailgun.com/pricing/
