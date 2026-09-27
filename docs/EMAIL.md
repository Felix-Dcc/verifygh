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

Resend, over the SMTP interface Resend documents for Django at
<https://resend.com/django>.

SMTP rather than Resend's HTTP SDK, deliberately: Django's own backend already
handles multipart alternatives, connection reuse and timeouts, so there is no
extra dependency to keep patched and `EmailMultiAlternatives` works unchanged.

**Setting `RESEND_API_KEY` is the entire configuration.** `config/settings/base.py`
then fills in Resend's published connection details itself:

| Setting | Value |
|---|---|
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST` | `smtp.resend.com` |
| `EMAIL_PORT` | `587` |
| `EMAIL_HOST_USER` | `resend` |
| `EMAIL_HOST_PASSWORD` | `RESEND_API_KEY` |
| `EMAIL_USE_TLS` | `True` |

An explicit `EMAIL_BACKEND` still wins, so development keeps the console
backend and the test suite keeps the in-memory one.

### Production will not boot without a real mailer

`config/settings/prod.py` refuses to start if:

* `EMAIL_BACKEND` is the console, file, dummy or in-memory backend;
* `RESEND_API_KEY` is set but is not shaped like a Resend key (`re_...`);
* SMTP is selected with no host or no password;
* `DEFAULT_FROM_EMAIL` is not a full address, or sits on a reserved domain;
* `REQUIRE_EMAIL_VERIFICATION_FOR_PURCHASE` is false.

`tests/test_startup_safety.py` boots each of these in a fresh interpreter and
asserts the refusal. An email that goes to stdout is indistinguishable, from the
application's point of view, from one that was delivered - so the only reliable
place to catch it is at boot.

## Environment variables

```
RESEND_API_KEY=          # secret. Dashboard only, never in git
DEFAULT_FROM_EMAIL=VerifyGH <no-reply@verifygh.com>
FRONTEND_URL=https://verifygh.com
EMAIL_VERIFICATION_TTL_HOURS=24
```

The API key is a **server-side secret**. It is never sent to the browser, never
logged, and `.env.example` carries an empty placeholder only. Anything
`NEXT_PUBLIC_*` ends up in the JavaScript bundle, so the key must never be
given a name like that.

## Verifying the sending domain in Resend

Until a domain is verified, Resend will only deliver to the account owner's own
address. That is enough to prove the pipeline works and not enough to sign up a
single customer.

In Resend: **Domains -> Add Domain**, enter the sending domain, and Resend
generates the DNS records. It recommends sending from a subdomain
(`mail.verifygh.com`) rather than the root domain.

Resend generates three kinds of record:

| Kind | What it does |
|---|---|
| `MX` | lets recipients return bounce and complaint feedback |
| `TXT` (SPF) | names who may send for the domain |
| `TXT` (DKIM, at `resend._domainkey`) | the public key recipients check the signature against |

**The values come from the Resend dashboard and are different for every
domain** - they are not written down here, because a guessed DKIM key is just a
domain that fails authentication. Copy each one from Resend exactly.

Two things that routinely go wrong at a DNS provider:

* paste only the host part (`resend._domainkey`, or `send`), not the full name
  with the domain appended - most providers add the domain themselves, and a
  pasted full name becomes `resend._domainkey.verifygh.com.verifygh.com`;
* if the domain is behind a CDN, set these records to **DNS only**, not proxied.

Verification usually completes within about 15 minutes, occasionally up to 72
hours. Then set `DEFAULT_FROM_EMAIL` to an address on the verified domain.

Consider a DMARC record once DKIM and SPF pass; Resend documents this
separately.

## The flow

```
register  ->  account, is_email_verified = false
          ->  SecurityToken.issue(EMAIL_VERIFICATION)   # 32 random bytes
          ->  only the SHA-256 hash is stored
          ->  Celery: send_verification_email
          ->  Resend  ->  inbox
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
