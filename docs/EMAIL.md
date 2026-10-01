# Transactional email

VerifyGH sends one kind of email that the product cannot work without: the
address verification link. Email verification is what stops one person opening
accounts on other people's addresses, and it gates every purchase, so a mailer
that does not deliver is not a cosmetic problem - it makes the gate
unsatisfiable.

## What was wrong

`EMAIL_BACKEND` defaulted to Django's **console backend**, and nothing in the
Railway configuration ever set it. Every verification email since the first
deploy was written to the container's stdout.

Nothing looked broken, which is why it went unnoticed:

* the console backend accepts every message and reports success, so
  `EmailMultiAlternatives.send()` returned normally;
* `notify()` recorded the notification as `SENT`;
* registration returned 201 with a valid session;
* the token row existed and the link would have worked - nobody ever received
  one.

Two smaller faults in the same area: `DEFAULT_FROM_EMAIL` defaulted to
`no-reply@verifygh.example`, and `.example` is a reserved TLD that real
providers reject outright (the same mistake that made Paystack refuse charges);
and `notify()` returned notification objects whose `delivery_status` had been
written with a queryset `update()`, so a caller reading the returned object
always saw `PENDING`.

## How it works now

Every email goes one way, through one place:

```
notify(user, event=..., channels=("EMAIL", ...))   apps/notifications/services.py
  -> EmailChannel                                   apps/notifications/channels.py
       renders the .txt template (or the message text) and an HTML part
       (its own .html template, or the shared layout emails/notification.html)
  -> EmailMultiAlternatives -> EMAIL_BACKEND
  -> BrevoEmailBackend                              apps/notifications/brevo.py
       POST https://api.brevo.com/v3/smtp/email  (header: api-key)
```

No other code knows the provider: changing it again means replacing the last
step only. The emails that go out this way:

| Event | Email | Template |
|---|---|---|
| `ACCOUNT_CREATED` | Verify your email address | `emails/verify_email.txt` / `.html` |
| `SECURITY_ALERT` | Reset your password | `emails/password_reset.txt` / `.html` |
| `SECURITY_ALERT` | Your password was changed | shared layout |
| `PAYMENT_SUCCESSFUL` / `PAYMENT_FAILED` | Deposit received / failed | shared layout |
| `ORDER_COMPLETED` | Order completed | shared layout |
| `REFUND_ISSUED` | Refund issued | shared layout |
| `ACCOUNT_SUSPENDED` | Account suspended | shared layout |
| `STAFF_*`, `PROVIDER_*` | Staff alerts (failed orders, reports, provider funding) | shared layout |

Referral bonuses, number-issue updates, assigned numbers, codes and expiries are
in-app only.

**Brevo's transactional email API, not SMTP.** HTTPS on 443 works from any
host: Railway blocks the standard SMTP ports, and a blocked port looks exactly
like a slow mail server. And when Brevo refuses a message, the API says why.

**Setting `BREVO_API_KEY` switches it on.** `config/settings/base.py` then uses
`apps.notifications.brevo.BrevoEmailBackend`. An explicit `EMAIL_BACKEND` still
wins, so development keeps the console backend and the test suite the in-memory
one. The tests that exercise Brevo replace its API with a fake (the `brevo`
fixture in `tests/conftest.py`), so no test sends a real email.

### When Brevo refuses

An email failing never fails what triggered it. Registration, a payment, a
refund or a purchase completes, and the notification is recorded as `FAILED`
with the reason. The verification email task tries again, and customers can
ask for another link.

The reason is written for staff, in the log (`brevo_email_refused`) and on the
notification row. Customers never see Brevo's words, and the API key and
recipient addresses are never logged.

| Brevo answers | Recorded as | Retried |
|---|---|---|
| 401 `unauthorized` | the key is wrong or revoked, or Brevo is blocking this server's IP address | no |
| 400 about the sender | the sender or its domain is not verified in Brevo | no |
| 400 `invalid_parameter` | Brevo refused the email, with its reason | no |
| 402 / `not_enough_credits` | the account has no email credits left | no |
| 429 | rate-limited | yes |
| 5xx, timeout, network | Brevo unavailable | yes |
| no `BREVO_API_KEY` | not configured; nothing is called | - |

A recipient that is not an email address is refused before Brevo is called.

### Production will not boot without a real mailer

`config/settings/prod.py` refuses to start if:

* `EMAIL_BACKEND` is the console, file, dummy or in-memory backend - in practice,
  `BREVO_API_KEY` is not set (and if only the old `RESEND_API_KEY` is, it says
  that is no longer used);
* `BREVO_API_KEY` is not shaped like a Brevo API key (`xkeysib-...`). The SMTP
  key Brevo also shows you (`xsmtpsib-...`) does not work with the API;
* Brevo is in use with no `BREVO_SENDER_EMAIL`;
* the sender is not a full address, or sits on a reserved domain;
* SMTP is selected by hand with no host or no password;
* `REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE` is false.

`tests/test_startup_safety.py` boots each of these in a fresh interpreter and
asserts the refusal.

## Environment variables

On **verifygh** (the API) and **verifygh-worker** - the worker sends most email:

```
BREVO_API_KEY=                 # secret: xkeysib-... Railway only, never in git or chat
BREVO_SENDER_EMAIL=support@getverifygh.com
BREVO_SENDER_NAME=VerifyGH
FRONTEND_URL=https://www.getverifygh.com
EMAIL_VERIFICATION_TTL_HOURS=24
SUPPORT_EMAIL=support@getverifygh.com   # optional; shown in every email's footer
```

`BREVO_SENDER_EMAIL` and `BREVO_SENDER_NAME` make the From address
(`"VerifyGH" <support@getverifygh.com>`); without them `DEFAULT_FROM_EMAIL` is
used. `RESEND_API_KEY` is no longer read - delete it from Railway once Brevo
works.

The API key is a **server-side secret**. It is never sent to the browser and
never logged, and `.env.example` carries an empty placeholder only.

## Setting up Brevo

Brevo will not deliver from `getverifygh.com` until the domain is authenticated
and the sender verified there. Until then, sends are refused and recorded as
failures - so do these before relying on it:

1. **API key.** Brevo > *SMTP & API* > *API keys* > *Generate a new API key*.
   Copy the `xkeysib-...` key straight into Railway as `BREVO_API_KEY`, on
   verifygh and verifygh-worker. Never paste it anywhere else.
2. **Authenticate the domain.** Brevo > *Senders, Domains & Dedicated IPs* >
   *Domains* > *Add a domain* > `getverifygh.com`. Brevo shows the DNS records to
   create - typically a Brevo verification code (TXT), DKIM records and a DMARC
   record. **Copy each one exactly as Brevo shows it**: the values are unique to
   this account, and none are written here because a guessed DKIM key is just a
   domain that fails authentication.
3. **Create them in Cloudflare** (the domain's DNS is there): *DNS > Records >
   Add record*, the type, name and value Brevo gives. Set every one to
   **DNS only** (grey cloud), never proxied. Enter only the host part of a name
   (e.g. `brevo1._domainkey`), not the full name with the domain appended.
   There must be only **one** SPF (`v=spf1`) TXT record per name - if Brevo asks
   for an SPF include and one already exists on that name, add the include to it
   rather than creating a second record. Then press *Authenticate* in Brevo.
   It can take minutes, occasionally up to 48 hours.
4. **Verify the sender.** Brevo > *Senders* > *Add a sender*:
   `VerifyGH <support@getverifygh.com>`. Brevo emails that address a code, so the
   mailbox has to receive mail (Cloudflare Email Routing to your inbox works).
5. **Authorised IPs.** Brevo can block API calls from IP addresses it has not
   seen - its own help says it switches an API key to blocking after 30 days.
   Railway's outgoing addresses change between deploys, so under Brevo >
   *Security* > *Authorised IPs* turn the blocking **off** for API keys (or
   every email eventually fails with a 401).
6. **Send yourself one.** Register with an address you own, or use "Forgot
   password". The email arrives from `support@getverifygh.com`, and the log shows
   `brevo_email_accepted`. If it shows `brevo_email_refused`, the reason says
   which step above is unfinished.

The old Resend records in Cloudflare (`resend._domainkey`, and the `send` MX and
SPF records) can be deleted once Brevo is sending; they do nothing for Brevo.

## The flow

```
register  ->  account, is_email_verified = false
          ->  SecurityToken.issue(EMAIL_VERIFICATION)   # 32 random bytes
          ->  only the SHA-256 hash is stored
          ->  Celery: send_verification_email
          ->  Brevo   ->  inbox
user clicks  https://verifygh.com/verify-email/<token>
          ->  POST /api/v1/auth/email/verify/confirm/
          ->  token consumed (conditional UPDATE: single use)
          ->  is_email_verified = true
          ->  purchases allowed
```

Sending runs in a Celery task, so an unreachable mail server cannot hold the
registration response open for the SMTP timeout. If the *broker* is unreachable
the send falls back to inline; if that fails too, the account still exists
unverified and the user can request another link. Registration never fails
because of email.

### Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/v1/auth/email/verify/confirm/` | none | consume a token |
| `POST /api/v1/auth/email/verify/send/` | session | resend, signed in |
| `POST /api/v1/auth/resend-verification/` | none | resend by address |

`resend-verification/` answers identically for an unknown address, a verified
address and a suspended account - otherwise it would tell a stranger who has an
account here. It is throttled on the client IP **and** the submitted address:
per-IP alone would let one caller walk a list of addresses, and per-address
alone would let a botnet mail-bomb one inbox.

## Token security

| Requirement | How |
|---|---|
| Unpredictable | `secrets.token_urlsafe(32)` - 256 bits from the OS CSPRNG |
| Not stored in the clear | only `sha256(token)` is persisted |
| Expires | `EMAIL_VERIFICATION_TTL_HOURS`, default 24 |
| Single use | conditional `UPDATE ... WHERE used_at IS NULL` |
| Superseded on reissue | issuing marks every earlier live token used |
| Not interchangeable | `purpose` is part of the lookup, so a verification token cannot reset a password |
| Never logged | the raw token exists only in the URL |

Single use is enforced with a conditional UPDATE rather than a read-then-save.
Two requests carrying the same token would both pass an `is_valid` check - only
the row-level `used_at IS NULL` filter can decide between them. Exactly one
caller wins, which is what makes the guarantee hold when a mail client
prefetches the link at the same moment the user clicks it.

## Purchase protection

`apps/orders/services.py::check_purchase_eligibility` is the gate, and
`create_order` - the only function that debits a wallet for a purchase - calls
it before anything else. Putting it there rather than in each view means a
future endpoint inherits the check instead of having to remember it;
`tests/test_email_verification.py` asserts that wiring so it cannot be removed
quietly.

An unverified purchase attempt returns **403** with code `EMAIL_NOT_VERIFIED`.
This is server-side and cannot be bypassed by calling the API directly, which
the test suite checks explicitly.

Deposits are deliberately **not** gated. Verification protects spending;
blocking top-ups would let someone fund a wallet they then could not use, or
strand money in an account before the email arrived.

## Logging

Logged: the notification template, the user id, delivery success or failure,
the exception class and the provider's own message.

Never logged: the API key, the raw token, passwords, or the message body.
`tests/test_email_verification.py::test_no_log_line_carries_the_raw_token`
enforces the token rule, because a token in a log file is a working link in a
log file.
