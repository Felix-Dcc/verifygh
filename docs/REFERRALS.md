# Referrals and promotional credit

A VerifyGH user shares a code. A genuinely new person signs up through it and,
once they have verified their email **and topped up at least GH₵10 of their own
money**, receives **GH₵2 of promotional credit**. When that friend then
completes a number paid at least partly in cash, the person who invited them
receives **GH₵3 of promotional credit**. Both rewards follow real money - none
is paid for a bare sign-up (14 Oct 2026).

Promotional credit is not cash. It buys verifications and nothing else: it
cannot be withdrawn, transferred, converted, or refunded as money. This
document is about how that distinction is kept true in the database, not only
in the interface.

---

## The money model

There is still **one wallet per user and one ledger**. The wallet simply has
two buckets:

| | `balance` (CASH) | `promo_balance` (PROMO) |
|---|---|---|
| Where it comes from | Mobile Money deposits | referral bonuses |
| Spendable on verifications | yes | yes |
| Withdrawable | yes | **never** |
| Refunded as | cash | promotional credit |
| Counts toward `total_deposited` | yes | no (`promo_granted` instead) |

Every movement of either bucket is an ordinary `WalletLedgerEntry` with a
`funds` column, written by the same `post_entry` that writes every other
entry - same wallet row lock, same compare-and-set, same
`UNIQUE(wallet, idempotency_key)`, same per-wallet sequence. Promotional money
gets the guarantees real money gets, and the reconciliation job checks both
chains.

Three database constraints do the arguing, so no future code path can get this
wrong:

* `ledger_funds_allow_entry_type` - a `WITHDRAWAL` can only be `CASH`, and a
  `REFERRAL_BONUS` can only be `PROMO`. **Promotional credit has no exit.**
* `wallet_promo_balance_non_negative` - the promotional bucket cannot go
  negative, even under a bug.
* `ledger_arithmetic_consistent` (PostgreSQL) - every row's
  `balance_after` really is `balance_before ± amount`.

### Spending order: promotional credit first

`split_charge` spends promotional credit before cash. The user cannot withdraw
the promotional part, so spending it first is what makes it worth anything to
them - and it leaves their cash where a refund can return it as cash.

A purchase that uses both writes **two ledger entries**, one per bucket, inside
the same transaction as the order, each with its own idempotency key
(`order:<id>` for cash, `order:<id>:promo`). Affordability is judged on the two
together (`wallet.spendable`).

### Refunds keep the split

An order records how it was paid (`promo_amount`, `cash_amount`). A refund
returns each bucket to itself. For a partial refund the split is proportional,
and the rounding remainder goes to the **promotional** side, so the cash
returned is never more than its true share. Nothing ever converts promotional
credit into withdrawable cash - not a refund, not a reversal, not an admin.

---

## The programme

| Setting | Default | Where |
|---|---|---|
| `REFERRAL_PROGRAM_ENABLED` | `true` | env, then database |
| `REFERRAL_SIGNUP_BONUS_GHS` | `2.00` | env, then database |
| `REFERRAL_MAX_MONTHLY_SUCCESSFUL_REFERRALS` | `40` | env, then database |
| `REFERRAL_REQUIRE_PHONE_VERIFICATION` | `false` | env, then database |
| `REFERRAL_REQUIRE_FIRST_DEPOSIT` | `true` | env, then database |
| `REFERRAL_MIN_FIRST_DEPOSIT_GHS` | `10.00` | env, then database |
| `REFERRAL_REFERRER_BONUS_GHS` | `3.00` (0 turns it off) | env, then database |

The environment variables **seed** the `ReferralProgram` row the first time it
is read. After that the row is the source of truth, so a super admin changes
the bonus in the console without a deploy. Editing the environment later does
not move an existing row.

---

## Codes

`VGH` plus five characters from an alphabet with no `0`, `1`, `I` or `O`, from
`secrets` - about 33 million combinations, non-sequential and safe to read
aloud. One per user (`OneToOne`), unique and indexed, normalised to upper case
on the way in, and never regenerated or chosen by the user.

The link is `https://<frontend>/register?ref=VGH8K4P2`.

---

## Attribution

The frontend reads `?ref=` and keeps it for the registration (sessionStorage,
per tab), then sends it with the sign-up. **It is never trusted.** The backend
resolves the code, decides whether it counts, and writes the attribution
itself, inside registration.

`Referral.referred_user` is a `OneToOne`, so an account has exactly one
referrer for ever. A `CHECK` constraint makes self-referral impossible at the
database level. There is no endpoint that changes a referrer, and a second
attempt returns the original row.

An unknown, inactive or suspended code is ignored: the person is registered
normally, with no referral and no error.

---

## Eligibility

Status is explicit: `PENDING` → `ELIGIBLE` → `REWARDED`, or `REJECTED`, or
`FRAUD_FLAGGED` (held for a human).

Evaluated in this order, cheapest and least ambiguous first, so an ordinary
user waiting on verification is never shown anything about fraud:

1. the programme is enabled;
2. referrer and referred user are different accounts;
3. neither account is suspended or inactive;
4. the referred user's email is verified;
5. their phone is verified, if the programme requires it;
5b. they have topped up at least `min_first_deposit` of their own cash, in
   total (ledger `DEPOSIT` entries; staff adjustments and promo do not count),
   if the programme requires it;
6. they have not already had a signup bonus (checked against the **ledger**,
   not only the reward table - even an admin's approval cannot pay a second);
7. no blocking risk flag - if there is one, the referral is held for review;
8. the referrer is under their monthly cap - if not, it is held, not rejected;
9. the referral has not already been rewarded.

Evaluation runs when the user verifies their email, when a deposit is
credited to them, when an admin acts, and every 30 minutes from
`process_pending_referrals`, which catches anything that became eligible later.

### The inviter's reward

`ReferrerReward`, one per referral (OneToOne), paid by `issue_referrer_reward`
when all of these hold:

* the friend's own bonus was paid and has not been reversed;
* the friend has a **completed** order with a delivered code, some of it paid in
  **cash**, and not refunded - a number bought with the bonus alone earns
  nothing;
* the inviter is active and not suspended, and the programme is running.

It runs when one of the friend's orders completes, right after the friend's own
bonus is paid (in case they bought while it was held), and in the same 30-minute
sweep. The ledger key is `referrer-reward:<referral id>`, so it is never mistaken
for a welcome bonus. The inviter is emailed when a friend joins with their code
and when they earn.

---

## Anti-abuse

| Signal | Level | Effect |
|---|---|---|
| Same email as the referrer (compared as inboxes: Gmail dots and `+tags`) | HIGH | held for review |
| Same inbox as any existing account (`canonical_email`) | HIGH | held for review |
| Same phone as the referrer | HIGH | blocked at registration (the phone is already unique) |
| Same device as the referrer | HIGH | held for review |
| Device shared with 2+ other accounts | MEDIUM | held for review |
| Referrer velocity (default 40/hour) | MEDIUM | held for review |
| Referrer at monthly cap | LOW | held until next month |
| Already had a signup bonus | MEDIUM | rejected |
| **Shared IP address** | LOW | **recorded only, never blocking** |

A shared IP address never withholds a reward on its own. Homes, offices,
schools, hostels and Ghanaian mobile networks all put many legitimate people
behind one address. Every flag is a `ReferralRiskFlag` row with a kind, a
level and a human-readable reason, visible to staff and never to customers -
telling someone which check caught them is a tutorial in evading it.

---

## API

| Endpoint | Who | What |
|---|---|---|
| `GET /api/v1/referrals/me/` | the user | code, link, bonus, stats |
| `GET /api/v1/referrals/stats/` | the user | successful / pending / rejected / issued |
| `GET /api/v1/referrals/history/` | the user | their invitations, emails masked |
| `POST /api/v1/referrals/validate/` | anyone (throttled) | is this code usable? nothing about its owner |
| `GET /api/v1/admin/referrals/` | staff | full list, filters, search |
| `POST /api/v1/admin/referrals/<id>/approve\|reject\|flag/` | admin | decide, with a reason |
| `POST /api/v1/admin/referrals/<id>/reverse-reward/` | super admin | claw back credit |
| `GET /api/v1/admin/referrals-analytics/` | staff | programme numbers |
| `GET\|PATCH /api/v1/admin/referral-program/` | staff / super admin | programme configuration |

**There is no claim endpoint.** The backend decides eligibility and issues the
reward; a "claim" button would be the browser asking to be given money.

---

## Idempotency

Calling the reward path ten times concurrently credits the bonus once. Three
independent mechanisms, any one of which would be enough:

1. `SELECT ... FOR UPDATE` on the referral row (PostgreSQL);
2. `ReferralReward.referral` is a `OneToOne`;
3. the ledger entry's idempotency key is `referral:<referral id>`, and the
   ledger already refuses a repeated key.

Together they also hold on SQLite, which has no row locks.

---

## Turning it on in production

1. Set the environment variables (or accept the defaults):
   ```bash
   REFERRAL_PROGRAM_ENABLED=true
   REFERRAL_SIGNUP_BONUS_GHS=2.00
   REFERRAL_MAX_MONTHLY_SUCCESSFUL_REFERRALS=40
   ```
2. Deploy and run `python manage.py migrate`. This adds the promotional bucket
   to existing wallets (`0.00`), the `funds` column to existing ledger rows
   (all `CASH`), and the four referral tables. It is additive: no existing row
   changes meaning.
3. Confirm the Celery beat schedule includes `process-pending-referrals`
   (every 30 minutes). Without it, referrals that become eligible later are
   only settled when the user next verifies something.
4. In the admin console, open **Referrals** and check the programme row reads
   as you expect. Change the bonus there, not in the environment.
5. Decide the budget. The cap is per referrer per month
   (`max_monthly_successful_referrals`); the programme has no global ceiling,
   so watch **Credit issued** on the referrals dashboard in the first weeks.
6. To pause at any time, use **Pause programme** on Admin → Referrals. It needs
   the pricing permission, and the reason you give goes into the audit log.
   While the programme is paused:
   * new sign-ups are not linked to referrers, and no bonus is paid;
   * customers see no "Refer friends" link anywhere;
   * /refer shows only a "paused" notice and their past invitations;
   * an invite link opens a plain sign-up page.

   Credit already granted is untouched, and codes work again when you press
   **Resume programme**. `REFERRAL_PROGRAM_ENABLED` only seeds the setting the
   first time; after that the console switch is what counts. The app reads it
   from `GET /api/v1/referrals/status/`.

### Before the first campaign

* Promotional credit is a liability you have promised to honour, not revenue.
  It is reported separately (`promo_granted`, `promotional_credit_issued`) -
  keep it out of deposit and revenue figures.
* Decide who reviews `FRAUD_FLAGGED` referrals, and how often. They are held,
  not rejected, so nobody is punished by silence - but nobody is paid either.
* Consider whether the terms of your Mobile Money aggregator or your published
  Terms need a line about promotional credit before you advertise it.
