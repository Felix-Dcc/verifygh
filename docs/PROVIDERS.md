# Verification providers

Written 2026-09-29, when TextVerified replaced OnlineSim as the intended
primary provider. Every claim about TextVerified cites its own published
pages, read that day. Where they are silent, it says **NOT DOCUMENTED /
REQUIRES PROVIDER CONFIRMATION**.

```
Customer -> VerifyGH -> provider router -> TextVerified   (primary, awaiting authorisation)
                                         -> Provider B     (future)
                                         -> Provider C     (future)
```

## 1. The one thing to know

**TextVerified's terms do not currently permit VerifyGH's business model.**
From its Terms and Conditions, section "Phone Numbers":

> Sharing these numbers to third parties is prohibited, considered a breach of
> these Terms, and may lead to immediate termination of your account.

VerifyGH buys a number and gives it to a Ghanaian customer. That is sharing it
with a third party. Its FAQ adds that TextVerified is "not a reseller" and that
"your verification is yours alone", and its support told us in September 2026
that it has no reseller arrangements (docs/PROVIDER_INTEGRATION.md).

One official page points the other way. The API overview
(textverified.com/automate) says the API "can be used to create your own
products with our rentals and verifications. Serve your users with quality
Non-VoIP US phone numbers". That conflicts with the terms, and only
TextVerified can resolve it, in writing.

So the integration is **built, tested and switched off**:

* TextVerified is registered, selected as the production provider, and may be
  synced, priced and balance-checked with our own account.
* Nothing is listed to customers, charged for, or ordered through it until
  staff record TextVerified's written permission in **Admin > Providers**
  (`Provider.resale_authorized`, with the evidence).
* We do not disguise VerifyGH as an ordinary end user, open further accounts,
  or proxy anything the terms prohibit.

### What to ask TextVerified

Their FAQ invites "power users" to "send us a message and we can discuss bulk
pricing and/or increasing the number of concurrent verifications". Send, from
the account holder, to support@textverified.com (or via textverified.com/contact-us):

1. VerifyGH sells one-time US verification numbers to customers in Ghana,
   bought through your API with our account. Your terms prohibit sharing
   numbers with third parties, while your API page invites building products
   that serve "your users". Do you permit this use, and on what terms?
2. If yes, please confirm in writing, and tell us about any reseller, partner
   or business agreement required.
3. Is there any postpaid, invoiced or credit arrangement for business accounts?
4. What is our account's limit on concurrent unfinished verifications, and can
   it be raised?
5. What rate limits apply to pricing, inventory and verification creation?

When they say yes in writing, a super admin records it in Admin > Providers >
TextVerified > "Record written authorisation" with the evidence (who, how,
when). Nothing else needs to change.

## 2. What TextVerified's official documentation says

Sources: API reference (textverified.com/docs/api/v2, from the OpenAPI document
at backend.textverified.com/swagger/v2/swagger.json, v2, OpenAPI 3.0.4, 49
paths, unchanged from our recorded copy in
`backend/apps/verification/textverified_endpoints.json`), Terms
(textverified.com/terms), FAQ (textverified.com/faq), API overview
(textverified.com/automate).

| # | Question | Answer |
|---|---|---|
| 1 | Official API docs | Yes: OpenAPI v2, above. |
| 2 | Authentication | `POST /api/pub/v2/auth` with headers `X-API-USERNAME` (account email) and `X-API-KEY` returns a bearer token with an expiry. We cache it until shortly before expiry. |
| 3 | Base URL | `https://www.textverified.com` (the `servers` entry). |
| 4 | Endpoints used | `auth`, `services`, `pricing/verifications`, `inventory/verifications`, `verifications` (create), `verifications/{id}` (details), `verifications/{id}/cancel`, `verifications/{id}/report`, `sms`, `account/me`. Nothing outside the spec is called; `tests/test_provider_safety.py` fails on any path not in it. |
| 5 | Service availability | `GET /services` (name, description, capability `sms`/`voice`/`smsAndVoiceCombo`); stock per service from `POST /inventory/verifications` (`availableQuantity`). |
| 6 | Country selection | **US only.** No country parameter or endpoint; FAQ: "Our numbers are all based in the US". **Canada is not available.** |
| 7 | Purchase | `POST /verifications` with `serviceName`, `capability`, optional `maxPrice`, and an `Idempotency-Key` header; 201 returns a link to the new verification. |
| 8 | SMS retrieval | `GET /sms?reservationId=...` or the `sms` link on the verification. Codes come pre-parsed (`parsedCode`). |
| 9 | Lifecycle | Verification states: `verificationPending`, `Completed`, `Canceled`, `TimedOut`, `Reported`, `Refunded`, `Reused`, `Reactivated`. FAQ: 5-15 minutes to receive a code depending on the service. |
| 10 | Cancellation | `POST /verifications/{id}/cancel`. |
| 11 | Refunds | `POST /verifications/{id}/report` for a number that did not work (FAQ: "We will refund you"). FAQ: "We only deduct credits if a verification comes in." Money refunds of purchased credit: case by case, never for crypto (Terms). |
| 12 | Webhooks | Yes, signed: HMAC-SHA512 of the raw body with the account's `whsec_...` secret, Base64, in `X-Webhook-Signature: HMAC-SHA512=...`. Events include `v2.sms.received` (carries `reservationId`). Retried with backoff; disabled after repeated failures. Configured in the TextVerified dashboard. The docs recommend webhooks for production but permit polling. |
| 13 | Rate limits | The API "may return 429" for auth, service list, pricing, inventory and reservation-changing requests; "limits may change". Numbers: **NOT DOCUMENTED / REQUIRES PROVIDER CONFIRMATION.** Guidance: reuse tokens, cache lookups, back off with jitter, one reservation change at a time per account. |
| 14 | Pricing | Yes: `POST /pricing/verifications` returns `price` per service (USD). |
| 15 | Account balance | Yes: `GET /account/me` returns `currentBalance`. Nothing reported as held/frozen. |
| 16 | Account funding | **Prepaid credits**, bought by card (Stripe) or cryptocurrency on the website (Terms; FAQ "Credits"). **No API adds money.** Postpaid/credit/invoicing: **NOT DOCUMENTED / REQUIRES PROVIDER CONFIRMATION.** |
| 17 | Business/reseller | FAQ: "We are not a reseller"; support (Sept 2026): no reseller arrangements. Bulk pricing for power users on request. |
| 18 | Acceptable use | Terms: no illegal activity; 13+; one account per person ("Creation of multiple accounts to avoid a ban ... is not allowed"). |
| 19 | Resale terms | **Prohibited** as written: "Sharing these numbers to third parties is prohibited". |
| 20 | VerifyGH's model permitted? | **No, not without written permission.** See section 1. |

Concurrency limit: the API has a `TooManyUnfinishedVerifications` error and the
FAQ offers to raise concurrency on request; the number itself is **NOT
DOCUMENTED / REQUIRES PROVIDER CONFIRMATION**. `MAX_PLATFORM_ACTIVE_ORDERS`
stays at 32 until TextVerified gives us the figure.

## 3. Capabilities, as implemented

| Interface operation | TextVerified | Status |
|---|---|---|
| `get_services` | `GET /services` + `POST /pricing/verifications` per service | Implemented. Paced: see section 6. |
| `get_countries` | none | Implemented as US only (the documented fact, not a guess). |
| `get_pricing` | `POST /pricing/verifications` | Implemented. |
| `get_availability` | `POST /inventory/verifications` | Implemented; checked live before every charge. |
| `create_order` | `POST /verifications` + `Idempotency-Key` + `maxPrice` | Implemented. |
| `get_order_status` | `GET /verifications/{id}` | Implemented. |
| `get_verification_code` | `GET /sms?reservationId=` | Implemented. |
| `cancel_order` | `POST /verifications/{id}/cancel` | Implemented. |
| `refund_order` / `report_number_issue` | `POST /verifications/{id}/report` | Implemented. |
| `get_balance` | `GET /account/me` | Implemented. |
| `fund_account` | none | **NOT SUPPORTED BY TEXTVERIFIED.** Raises; never called. |
| `parse_webhook` | signed `v2.sms.received` | Implemented, as a prompt to poll only. |
| Canada numbers | none | **NOT SUPPORTED BY TEXTVERIFIED.** |

## 4. Order lifecycle

VerifyGH's existing states are kept - renaming them would break every
historical order and the customer app. How the requested lifecycle maps:

| Requested | VerifyGH | Notes |
|---|---|---|
| CREATED | `CREATED` | Only inside the purchase transaction. |
| Wallet funds reserved | `PROCESSING` | Debited through the double-entry ledger in the same transaction as the order. |
| PROVIDER_REQUESTED | `PROCESSING` + `provider_order_id` | `create_order` runs after commit, never holding a wallet lock. |
| NUMBER_ASSIGNED | `NUMBER_ASSIGNED` | |
| WAITING_FOR_SMS | `WAITING_FOR_CODE` | |
| SMS_RECEIVED | `CODE_RECEIVED` | |
| COMPLETED | `COMPLETED` | |
| PROVIDER_FAILED | `FAILED` | |
| REFUND_PENDING | `refund_status=PENDING` | |
| REFUNDED | `REFUNDED` | Automatic for every provider failure. |
| CANCEL_REQUESTED / CANCELLED | `CANCELLED` | |

Before any money moves, a purchase checks, in order: eligibility and limits,
that the country is sold (US only, server-side), that the provider is
enabled + registered + **authorised to resell**, that our provider balance
covers it, and live stock. After the charge, fulfilment checks enabled +
authorised again (either can change in between) and refunds without calling
the provider if not.

## 5. Idempotency and the provider transaction id

* A purchase carries the customer's idempotency key: a double tap or client
  retry returns the same order (`order_idempotency_unique`).
* The provider call carries `Idempotency-Key: vgh:<order id>`, which
  TextVerified documents: a retry after a timeout cannot reserve a second
  number.
* The verification id is stored as `Order.provider_order_id`, now unique per
  provider (`order_provider_order_id_unique`): one upstream reservation can
  never belong to two orders.
* Each order keeps its provider, provider cost and currency, the exchange
  rate, the full pricing breakdown, the customer price, timestamps and status.

## 6. Pricing and the catalogue

TextVerified exposes pricing, so its costs come from its API - never typed in.
Pipeline unchanged: provider cost (USD) x VerifyGH Pricing FX Rate -> cost in
GHS -> markup -> customer price. A service that cannot be priced is left out.

Each price is a separate call and pricing may be rate limited, so one catalogue
sync prices up to `PROVIDER_CATALOG_LIMIT` services (0 = no count limit) within
60 seconds, stops at the first 429, and the next sync resumes where it
stopped. Services not priced in a run keep their last known price. With a
large catalogue, full coverage takes several syncs (every 3 hours, or run one
from Admin > Catalog).

`maxPrice` is sent on every purchase at the synced price x
`PROVIDER_PRICE_TOLERANCE` (1.05), rounded up to the cent, so a price rise
beyond 5% is refused upstream and refunded rather than silently billed to us.

## 7. Funding

TextVerified is prepaid, exactly like OnlineSim was: **the prepaid bottleneck
has not gone away.** Customer deposits never reach TextVerified. A super admin
buys credits by card or crypto on textverified.com and records the top-up in
Admin > Provider funding. The balance is read every 2 minutes from
`account/me`; purchases the balance cannot cover are refused before charging;
staff are alerted when it runs low. TextVerified publishes no idle-account
deletion rule (OnlineSim's 30-day rule is not applied to it). See
docs/PROVIDER-FUNDING.md.

## 8. Errors

Customers never see provider responses. Mapping:

| TextVerified | Customer sees | Staff see |
|---|---|---|
| `InsufficientBalance` | Order refunded, "temporarily unavailable" | PROVIDER_REFUSED alert with the code; balance re-read |
| `Unavailable` / zero inventory | "No numbers available", nothing charged | - |
| `PricingFailure` (price moved past `maxPrice`) | Order refunded | log |
| `TooManyUnfinishedVerifications` | Order refunded | log |
| 401/403 | Order refunded | API_UNAVAILABLE alert via the balance sync |
| 429 | "busy, try again", nothing charged when before payment | log; sync stops and resumes |
| Timeout / 5xx | Refunded, or retried by the next poll | log |

## 9. SMS retrieval

Polling through the existing Celery beat (`poll-active-orders`, every 10
seconds, only for orders actually waiting), inside the provider call budget
(`PROVIDER_RATE_LIMIT_PER_MINUTE`). The customer's browser polls our API, never
TextVerified.

Optionally, set `TEXTVERIFIED_WEBHOOK_SECRET` and point TextVerified's webhook
settings at `https://api.getverifygh.com/api/v1/verification/webhooks/textverified/`,
subscribed to `v2.sms.received`. A callback with a valid signature queues an
immediate poll of that order; the code is only ever taken from the
authenticated API, never from the callback body. Without the secret the
endpoint answers 404.

The docs do not say whether the `whsec_` secret is used as written or with
its encoded part decoded; both are accepted, since both need our secret.
**Confirm with the first real webhook** (Admin > Providers shows it working).

## 10. Credentials and configuration

| Variable | Required | Notes |
|---|---|---|
| `VERIFICATION_PROVIDER` | yes | `textverified` in production. Production refuses `mock` and any provider without its credentials, at boot. There is no fallback. |
| `TEXTVERIFIED_API_USERNAME` | yes | The TextVerified account email. |
| `TEXTVERIFIED_API_KEY` | yes | From the TextVerified dashboard. Secret: never logged, never sent to the browser. |
| `TEXTVERIFIED_BASE_URL` | no | Leave empty for the documented host. |
| `TEXTVERIFIED_WEBHOOK_SECRET` | no | Enables signed webhooks (section 9). |
| `ONLINESIM_*` | no | Legacy; remove once no OnlineSim order is in flight. |

## 11. Removing OnlineSim

OnlineSim stopped being the active provider on 2026-09-29. Its provider row is
switched off, so it is neither sold, synced, balance-checked nor
health-checked. Nothing historical was deleted: its 5 orders, 14,900 catalogue
rows, price and cost history, funding records and audit entries remain, and
`Provider(adapter_key="onlinesim")` stays valid for them.

**OnlineSim still holds about $5.05 of our credit.** Its terms delete an
account 30 days after its last completed purchase (28 Sep 2026), forfeiting
the balance: use it or ask OnlineSim for a refund before 28 Oct 2026.

Every reference in the repository, classified:

| Class | Where | What happened |
|---|---|---|
| A. Provider implementation | `apps/verification/onlinesim.py` | Kept, dormant: registered so its orders keep their history and could be settled. |
| B. Configuration | `config/settings/base.py` credentials block | Kept, marked legacy. |
| C. Tests | `tests/test_onlinesim.py` and others | Kept: they test the dormant adapter and history. Baselines moved to TextVerified. |
| D. Documentation | `docs/PROVIDER_INTEGRATION.md`, `docs/PROVIDER-FUNDING.md`, `docs/DEPLOYMENT.md`, `README.md` | Updated; this file is now the entry point. |
| E. Database migration | `catalog 0002`, `0006` | Unchanged history. New: `catalog 0009/0010` (resale authorisation; OnlineSim's recorded as of 2026-09-27), `orders 0005` (unique provider order id). |
| F. Admin UI | Provider funding page, pricing placeholder | Made provider-neutral. New Admin > Providers page. |
| G. Environment variables | `ONLINESIM_API_KEY`, `ONLINESIM_CURRENCY` on Railway | To remove after the switch (section 12). |
| H. Pricing | 14,900 OnlineSim offerings and their price/cost history | Kept, not sold. |
| I. Provider routing | `registry.py` | TextVerified registered first; routing now requires authorisation. |
| J. Deployment | `.railway/railway.ts` | `VERIFICATION_PROVIDER=textverified`; TextVerified variables added; OnlineSim ones removed. |
| K. Historical / audit data | orders, ledger, audit log, funding records | Untouched. |
| - | `onlinesim_endpoints.json`, `onlinesim_countries.json` | Kept: the dormant adapter's provenance. |
| - | Comments mentioning OnlineSim as an example | Updated where they described current behaviour; kept where historical. |

## 12. Switching production over

1. Deploy (done with this change): OnlineSim switched off; TextVerified row
   switched on, unauthorised. Customers see no services.
2. **You:** add `TEXTVERIFIED_API_USERNAME` and `TEXTVERIFIED_API_KEY` to the
   `verifygh`, `verifygh-worker` and `verifygh-beat` services in Railway.
   Never paste them into a chat.
3. Set `VERIFICATION_PROVIDER=textverified` on those services (before step 2
   it would refuse to boot, by design), and remove `ONLINESIM_API_KEY` and
   `ONLINESIM_CURRENCY`.
4. Run a catalogue sync; set prices in Admin > Pricing; buy credits on
   textverified.com and record the top-up.
5. **When TextVerified authorises resale in writing**, record it in Admin >
   Providers. Only then are services listed and sold.

## 13. Adding Provider B or C

Write an adapter implementing `VerificationProvider` from that provider's
official documentation only, register it, give its row a priority, and record
its written resale authorisation. The router already tries authorised,
enabled, registered, funded providers in priority order and fails over only
at or below the price the customer was shown.
