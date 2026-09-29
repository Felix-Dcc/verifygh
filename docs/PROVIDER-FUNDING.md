# Provider funding: keeping OnlineSIM able to sell

> **2026-09-29: TextVerified replaced OnlineSim as the intended primary
> provider, and it has the same problem.** It is funded with prepaid credits
> bought by card or cryptocurrency on its website (Terms; FAQ "Credits"), and
> `GET /api/pub/v2/account/me` only reads the balance. Postpaid, invoiced or
> credit terms are not documented. Everything below - the reserve, the guard,
> the alerts, the cash-flow view - applies to it unchanged, except OnlineSim's
> 30-day idle-account deletion, which TextVerified's terms do not have. See
> [PROVIDERS.md](PROVIDERS.md) section 7.

Written 2026-09-29. Research sources are OnlineSIM's own published pages, read on
that date; every claim below cites one. Where the pages are silent, the answer
is marked **UNKNOWN - requires confirmation from OnlineSIM**.

## 1. The problem

Customers pay VerifyGH in cedis (Mobile Money via Paystack) into their VerifyGH
wallet. When they buy a number, VerifyGH calls OnlineSIM's `getNum`, and
OnlineSIM draws the cost from **VerifyGH's own prepaid OnlineSIM balance**.
Money in customer wallets never reaches OnlineSIM by itself, so a customer
with GHS 100 in their wallet still cannot buy anything when the OnlineSIM
balance is empty.

Where it bites in the code today (traced through the repository):

```
Paystack webhook (HMAC-verified) -> wallet DEPOSIT ledger entry
POST /orders/  -> check_purchase_eligibility
               -> resolve_offering (one provider)
               -> confirm_live_availability (getTariffs: stock only)
               -> quote_for_offering
               -> atomic: Order + charge_order (wallet row lock, PURCHASE entry)
on_commit      -> fulfil_order_task -> provider.create_order (getNum)
                    getNum -> WARNING_LOW_BALANCE -> ProviderError
                 -> fail_order -> issue_refund (automatic, REFUND entry)
```

So nobody loses money - the refund is automatic and ledger-safe - but the
customer is charged, sees a failed order and a refund, and the ledger carries
a charge and a reversal for a purchase that could never have succeeded. The
balance is only discovered to be empty *after* the customer has been charged.

At the time of writing the live OnlineSIM balance was **$5.05** (nothing
frozen), and customer wallets held **GHS 30.00**.

## 2. What OnlineSIM actually offers

| Question | Answer | Source |
|---|---|---|
| How is the account funded? | **Prepaid.** "The Client prepays for the Marketplace Services by transfer to the Provider's bank account and/or by electronic or digital asset payment methods available on the Platform. Prepaid amounts are reflected as credits on the Client's Account." | Terms and Conditions 4.1 (updated 27 Feb 2026), onlinesim.io/documentation/offer |
| Payment methods | Card, cryptocurrency, phone balance, bank transfer; recharge codes sold on digiseller.market and activated by hand in the web account. | Terms 4.1; "Money isn't showing up in my balance"; "How to activate a recharge code" (onlinesim.io/instructions) |
| Postpaid / credit account / credit limit | **Not offered publicly.** Nothing in the Terms, API or help pages. Individual agreements: **UNKNOWN - requires confirmation from OnlineSIM.** | Terms; API reference |
| Invoicing / business contract | Bank transfer is accepted (Terms 4.1). Formal invoicing, a signed B2B contract or net terms: **UNKNOWN - requires confirmation from OnlineSIM.** | Terms 4.1 |
| Wholesale / reseller terms | **No.** "Do you have wholesale sales? No. We only have retail sales, we do not provide, accordingly, any discounts and promotions." | FAQ, onlinesim.io/instructions/frequently-questioned-answers |
| API to top up the balance | **No.** The API reference has getTariffs, getNum, getState, setOperationRevise, setOperationOk, the rent methods, getBalance, getFreeList and the newSms webhook. None moves money in. `getBalance` is documented as the way to "check the balance of the profile to top it up when needed". | onlinesim.io/openapi_docs (getBalance) |
| Automatic replenishment | **No** such feature is documented. | API reference; Terms |
| Funding webhook | **No.** The only webhook is `newSms` (incoming SMS). | API reference |
| Subaccounts / reseller wallets / white label | **Not documented.** **UNKNOWN - requires confirmation from OnlineSIM.** | API reference |
| Account-to-account transfer | **Not documented.** Balance "is a limited, non-transferable service credit, is not redeemable for cash". | Terms 11.5 |
| Buying without a prepaid balance | **No.** The account "may be debited upon allocation, reservation or activation" of a number. | Terms 4.3 |
| Frozen balance | Ordering a number freezes its price; it is debited if an SMS arrives and returned to the balance if not. `getBalance` reports it as `zbalance`. | FAQ ("What is a frozen balance?"); getBalance |
| Minimum balance / minimum top-up | **Not documented.** **UNKNOWN - requires confirmation from OnlineSIM.** | - |
| Referral programme | 5% of referred users' purchases (capped at $50 per referral). Earnings for bringing *other* customers to OnlineSIM - not a funding source for VerifyGH's own account. | onlinesim.io/referral |
| Developer programme (`dev_id`) | 5% of what *users of your software* spend from *their own* OnlineSIM accounts. VerifyGH's customers do not have OnlineSIM accounts, so it does not apply as designed. Whether VerifyGH may tag its own purchases with its own `dev_id` for a rebate: **UNKNOWN - requires confirmation from OnlineSIM**; do not do it without written approval. | onlinesim.io/instructions/connecting-your-software-to-our-service |
| "Cooperation" page | For people supplying SIM cards / GoIP gateways *to* OnlineSIM. Not relevant. | onlinesim.io/affiliate |
| Integrating the API into our product | Allowed; "your account will be held responsible for all actions taken by users". Standard limit 40 numbers on hold. | OnlineSIM support chat, 27 Sep 2026 (recorded in apps/verification/onlinesim_endpoints.json) |
| **Inactivity** | **The account is deleted 30 days after the last completed purchase, and any remaining balance is forfeited.** | Terms 11.4, 11.5; Refund Policy 2.4 |
| Refunds of balance | Case by case, by email, 3-5 business days, to the original payment method; none for network outcomes. | Refund Policy 2-4 |

### Conclusion

**OnlineSIM's commercial model requires provider-side funding. Software cannot
eliminate that requirement.** There is no documented postpaid, credit, reseller
or API-funding option, and the FAQ explicitly rules out wholesale. Automating
their web payment page to top up would mean driving their website with a bot,
which is out of bounds.

The best legitimate outcome is therefore: **keep a right-sized prepaid reserve
at OnlineSIM, see its level at all times, top it up by hand before it runs out,
never charge a customer for a purchase the reserve cannot cover, and fail over
to another provider only if one is authorised.**

## 3. The options

| Option | What it needs | VerifyGH can build it? | OnlineSIM must approve? | Verdict |
|---|---|---|---|---|
| A. OnlineSIM postpaid / credit | A credit agreement with OnlineSIM | Only the config switch; the arrangement itself is theirs | **Yes** - not publicly offered | Ask them. **Code cannot solve this until OnlineSIM approves/provides the required account type.** |
| B. OnlineSIM reseller account | A reseller programme | - | **Yes** - FAQ says retail only | Ask, expect "no". |
| C. API-supported automatic funding | A funding endpoint | No - none exists | Would need a new product from them | Not available. |
| D. Automated funding through a supported payment mechanism | e.g. an API to their payment processor | No - payment is through their web pages; automating those is not allowed | Yes | Not available. |
| E. Provider reserve (prepaid float, monitored) | Working capital, a routine, visibility | **Yes** | No | **Implemented.** The only option that works today. |
| F. Different provider with a better commercial model | A provider that offers credit/postpaid *and* permits resale | Yes, through the existing provider abstraction | That provider must authorise resale | Worth pursuing commercially; TextVerified already refused resale. |
| G. Hybrid multi-provider | Two or more authorised providers | **Yes** - router implemented | Each provider authorises | **Implemented** (routing + failover); only OnlineSIM is authorised today, so it is dormant. |

### Cash-flow reality of option E

The reserve is VerifyGH's working capital, not customer money. Customer
wallet balances are a **liability** (money owed to customers as future
purchases) and must stay available to honour them; VerifyGH's gross profit is
only `customer price - provider cost in cedis` on delivered orders. The
reserve should be funded from operating funds (profit and capital), never by
treating wallet balances as spendable.

Sizing: the reserve should cover the provider cost of several days of sales.
Today's volume is tiny (2 delivered orders in 30 days, $0.12 each), so the
default minimum $5 / target $20 is generous. Do not over-fund: **the Terms
forfeit the whole balance if the account goes 30 days without a completed
purchase.** VerifyGH now warns when the last purchase is 20+ days old.

## 4. Recommended architecture (implemented)

```
Customer --MoMo/Paystack--> Wallet (liability, double-entry ledger, unchanged)
   |
   v  POST /orders/
Provider router: offerings for (service, country), lowest priority/cost first,
                 authorised (registered + enabled) providers only
   for each candidate:
     provider funding guard  - cached balance (synced every 2 min) must cover
                               the provider cost with a margin, else skip
     live stock check        - getTariffs count
   none usable -> 503 "temporarily unavailable", nothing charged, staff alerted
   first usable -> price it (server side) -> atomic wallet debit + order
   -> getNum (after commit) -> success: number
                            -> failure (e.g. WARNING_LOW_BALANCE): automatic
                               refund (unchanged) + balance re-sync + alert

Beat task every 2 min: getBalance -> ProviderAccount (balance, frozen,
   status HEALTHY / LOW / CRITICAL / UNKNOWN, estimated purchases left)
   -> staff alerts on every change of status, sync failure, repeated API
      failures, failure spikes, unconfirmed top-ups and the 30-day inactivity risk

Staff: Admin > Provider funding
   balance, status, minimum / critical / target, recommended top-up,
   "Record a top-up" (amount, method, reference, GHS paid from operating
   funds), funding history, cash-flow view.
```

## 5. What OnlineSIM needs to be asked (commercial actions)

Send to support@onlinesim.io from the account holder:

1. Do you offer a postpaid, credit-limit or invoiced account for businesses
   integrating your API? If yes, the terms and how to apply.
2. Can a legal entity pay by bank transfer against invoices on a regular
   schedule, and is there a minimum amount?
3. Is there any reseller/partner arrangement with volume pricing? (FAQ says no.)
4. Does the 30-day inactivity deletion (Terms 11.4) apply to accounts with a
   positive balance used through the API, and can it be waived for us?
5. May we pass our own `dev_id` on our own `getNum` calls, or is the developer
   programme only for software whose users hold their own accounts?
6. Can the standard 40-numbers-on-hold limit be raised when we need it?

If (1) is ever a yes - and **only after** the arrangement is live and in
writing - a provider manager can switch that account's mode to "Credit
agreement" and enter the agreed limit (`ProviderAccount.mode` /
`credit_limit`); the funding guard then counts the limit as spendable. Until
then every account stays Prepaid. **Code cannot solve this until OnlineSIM
approves/provides the required account type.**

## 6. Credentials

None new. `getBalance` uses the existing `ONLINESIM_API_KEY`.

## 7. Code changes

* `apps/verification/base.py`: `BalanceDTO`, `supports_balance`,
  `get_balance()`, `supports_account_funding = False` and `fund_account()`,
  which raises `NotImplementedError` - implemented by no adapter, because no
  provider documents a funding API.
* `apps/verification/onlinesim.py`: `get_balance()` from `getBalance`
  (`balance` spendable, `zbalance` frozen). Documented error codes now travel
  on the exception (`provider_code`, `operational`) for staff alerts; the
  customer-facing message is unchanged and generic.
* `apps/verification/registry.py`: the rate-limited wrapper passes both through.
* `apps/verification/mock.py`: a settable balance per adapter, and
  `WARNING_LOW_BALANCE` when it cannot cover a number.
* `apps/funding/` (new): models, the balance sync and grading, the purchase
  guard, alerts, scheduled checks, top-up recording, the cash-flow report,
  the admin API and Celery tasks.
* `apps/orders/services.py`: `candidate_offerings` (enabled providers with a
  registered adapter only) and `purchasable_offering` (funding guard, then
  live stock, per candidate; failover never above the preferred price) run
  before any money moves. A provider refusal still fails and refunds exactly
  as before, and now also alerts staff and re-reads the balance.
* `apps/numbers/services.py`: a free replacement is refused, with the real
  reason for staff, when the balance cannot pay for it.
* `apps/catalog/marketplace.py` and the legacy `/services/` listing: offerings
  the last balance reading cannot pay for are not listed (same rule and
  price ceiling as the purchase); a balance change clears the cache.
* Celery beat: `sync-provider-balances` every 2 minutes.
* Settings (`VERIFYGH`): `PROVIDER_FUNDING_GUARD`, `PROVIDER_RESERVE_CRITICAL`
  / `_MINIMUM` / `_TARGET` (2 / 5 / 20, seeds for new accounts),
  `PROVIDER_ALERT_COOLDOWN_MINUTES`, `PROVIDER_SYNC_FAILURE_ALERT_AFTER`,
  `PROVIDER_FAILURE_SPIKE_THRESHOLD` / `_WINDOW_MINUTES`,
  `PROVIDER_INACTIVITY_DELETION_DAYS` / `_WARNING_DAYS`,
  `PROVIDER_TOP_UP_CONFIRM_HOURS`.
* Admin UI: `Admin > Provider funding` (`/admin/funding`).

## 8. Database changes

One migration, `funding 0001_initial`, adding three tables:

* `funding_provider_account` - one row per provider: mode, currency,
  spendable (`available`) and frozen balance, credit limit, critical /
  minimum / target levels, status, sync times, last error, failure streak.
* `funding_provider_top_up` - manual top-up records: amount, currency,
  method, external reference, GHS paid from operating funds, note, balance
  before, confirmation time and balance, who recorded it.
* `funding_provider_alert` - every alert with its real reason.

No change to the wallet ledger or any existing table. The provider balance
field is deliberately not called `balance`, so the ledger-boundary test keeps
guaranteeing that only the ledger service writes wallet balances.

## 9. Admin changes

`Admin > Provider funding`: per provider, the spendable and frozen balance,
status, recommended top-up, numbers it can still buy, days of cover, the
date the account would be deleted if idle, "Refresh balance", "Record a
top-up", "Reserve levels" and the top-up history; a cash-flow view that
separates customer funds (liability), provider balance, revenue, provider
cost, gross profit and funding need, headed "Customer wallet balance ≠
VerifyGH profit"; and the recent alerts.

## 10. Security

* Seeing the page needs `PRICING_VIEW` (admins and super admins - the same
  people who see provider costs). Changing reserve levels or recording a
  top-up needs `PROVIDER_MANAGE` (super admins). Support and customers get
  403. Every change is an `AdminAction` with a reason.
* Alerts go to active, unsuspended staff holding `PROVIDER_MANAGE`: in-app
  always, email for warnings and critical alerts.
* The system never moves money to OnlineSIM. A top-up record is bookkeeping
  for a payment staff made by hand; it cannot spend anything. A reference or
  note that looks like a card number (a Luhn-valid 13-19 digit run) is
  refused.
* Customers never see provider names or balance problems: a purchase the
  balance cannot cover is "This service is temporarily unavailable. Please
  try again shortly." (`TEMPORARILY_UNAVAILABLE`), with nothing charged.

## 11. Accounting

* Customer deposits stay in the wallet ledger as liabilities, untouched.
* A provider top-up is recorded as an operating payment (GHS paid, provider
  currency credited) in `funding_provider_top_up`, outside the customer
  ledger: a prepayment to a supplier, not a customer transaction and not a
  cost until numbers are bought with it.
* Provider cost of a sale remains the order's frozen pricing snapshot
  (`provider_cost` x the exchange rate on the order); gross profit = price
  minus that, over delivered orders only.

## 12. Failure scenarios

| Scenario | Behaviour |
|---|---|
| Balance below what a purchase needs | The balance is read live once (it may predate a top-up); if still short, other authorised providers are tried at or below the shown price; otherwise 503 "temporarily unavailable" before charging, and a PURCHASE_BLOCKED alert with the real reason |
| Balance below what an offering costs, while browsing | The marketplace (list, home, popular, purchase screen, landing page) does not list it, unless an authorised fallback at or below its price is funded. Uses the stored reading only - no provider call per page view - and the listing refreshes as soon as a new reading changes the balance |
| Balance never read | Treated as unknown, not zero: purchases proceed and the provider decides; the cash-flow view shows no shortfall figure |
| Balance read fails | The last reading and status are kept; SYNC_FAILED alert after 3 failures in a row; API_UNAVAILABLE at once for a blocked account or bad key |
| getNum says WARNING_LOW_BALANCE anyway (race, guard off) | Existing automatic refund; PROVIDER_REFUSED alert; balance re-read |
| Provider API outage | Live stock check fails -> 503 before charging; sync-failure alert |
| Many orders failing | FAILURE_SPIKE alert at 5 failures in 30 minutes |
| No completed purchase for 20+ days | INACTIVITY alert: OnlineSIM deletes the account and balance at 30 days |
| Recorded top-up not seen in the balance after 24 h | TOP_UP_NOT_REFLECTED alert |
| Two purchases race for the last dollar | Both may pass the guard; the loser is refunded automatically. No money is lost. |

## 13. Rollback

Set `PROVIDER_FUNDING_GUARD=false` to disable the pre-purchase balance check
(behaviour returns to charge-then-refund). The beat task and admin page never
move money and can be left running. To remove everything, revert the commit
and the `funding` migration; nothing outside `apps/funding` references its
tables.
