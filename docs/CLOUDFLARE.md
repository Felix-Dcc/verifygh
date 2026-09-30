# Putting VerifyGH behind Cloudflare

Written 2026-09-30. Cloudflare facts cite Cloudflare's own documentation, read
that day. Today (before this rollout) DNS is at the registrar
(`dns1/dns2.registrar-servers.com`) and every hostname is served straight from
Railway's edge.

```
Visitor -> Cloudflare (WAF, DDoS, bots, Turnstile) -> Railway -> Next.js / Django
                                                        |
                                    PostgreSQL, Redis, Paystack, TextVerified
```

## 1. What the code already does

Three problems would appear the moment Cloudflare is switched on. All three are
fixed in code, **off by default**, and switched on by variables once the DNS has
moved.

### Real client IPs

Cloudflare sends the visitor's address in `CF-Connecting-IP`, "only on the
traffic from Cloudflare's edge to your origin" (Cloudflare HTTP headers docs).
Without handling it, every customer behind one Cloudflare edge would look like
one IP and share one rate-limit bucket (5 password resets an hour, 30 logins a
minute) - real people locked out, bots barely slowed.

`apps/common/middleware.get_client_ip` now uses `CF-Connecting-IP` - but only on
requests carrying the origin secret below, because anyone reaching Railway
directly could write that header themselves. Every rate limit (DRF throttles
included, which used to read `X-Forwarded-For` on their own), audit log, login
record, device fingerprint and webhook record uses this one function.

`TRUSTED_PROXY_COUNT` stays `1`: it still describes Railway's edge, and it is
the fallback for anything that did not come through Cloudflare.

### An origin only Cloudflare can reach

The Railway addresses (`*.up.railway.app`, including the old API domain) would
still reach the servers directly, around Cloudflare's WAF, DDoS and bot
protection. So a Cloudflare **Request Header Transform Rule** sets
`X-VerifyGH-Origin` to a long secret on every request - it "overwrites its
previous value", so a visitor cannot supply it - and both the API (Django
middleware) and the website (Next.js middleware) check it:

| `CLOUDFLARE_MODE` | Effect |
|---|---|
| `off` (default) | Nothing checked. Today's behaviour. |
| `report` | Requests without the secret are **logged** (`request_not_via_cloudflare`), not refused. Requests with it get the real client IP. |
| `enforce` | Requests without the secret get **403**. |

Railway's health checks (host `healthcheck.railway.app`) are always let through.
Production refuses to boot with an unknown mode, or with `report`/`enforce` and
a missing or short (< 32 character) `CLOUDFLARE_ORIGIN_SECRET`.

Static files and link prefetches skip the website's middleware and so are not
origin-checked; they are public and run no application code.

### Turnstile allowed by the Content-Security-Policy

The site's CSP blocks every third-party frame and script. Cloudflare's
Turnstile CSP guidance: load `api.js` with the page's nonce (the site already
uses a nonce with `'strict-dynamic'`, which Turnstile supports) and allow
`https://challenges.cloudflare.com` in `frame-src` (and `script-src` for older
browsers). That is added **only when `NEXT_PUBLIC_TURNSTILE_SITE_KEY` is set**;
without it nothing is relaxed.

Adding the widget to forms, and verifying tokens on the server, is the next
step and is not part of this change.

## 2. Rollout

Order matters. Skipping step 1 can take email or the whole site offline.

### Step 1 - Recreate every DNS record in Cloudflare (before touching nameservers)

Add the site in Cloudflare (Free plan is enough to start). Cloudflare scans and
imports existing records; **check the import against the full list in the
registrar's DNS page**, not against memory. The public records found on
2026-09-30:

| Name | Type | Value | Proxy |
|---|---|---|---|
| `getverifygh.com` | A | `69.46.46.31` (Railway) | see step 3 |
| `www` | CNAME | `vr1mceja.up.railway.app` | see step 3 |
| `api` | CNAME | `olrej3wo.up.railway.app` | see step 3 |
| `resend._domainkey` | TXT | the DKIM key (copy the full value) | DNS only |
| `send` | TXT | `v=spf1 include:amazonses.com ~all` | DNS only |
| `send` | MX | `10 feedback-smtp.eu-west-1.amazonses.com` | DNS only |

Also copy anything else the registrar lists - the Resend "relay" CNAME noted in
`.railway/railway.ts`, any Railway verification TXT records. Email records are
never proxied.

In Resend, confirm the domain still shows **Verified** after the switch.

### Step 2 - Cloudflare settings before any traffic arrives

* **SSL/TLS mode: Full (strict).** Never "Flexible": that would carry traffic
  from Cloudflare to Railway unencrypted, and Railway redirects HTTP to HTTPS,
  which loops.
* **Rocket Loader: off. Email Address Obfuscation: off.** Both inject or rewrite
  scripts, which the site's nonce-based CSP blocks.
* **The origin-secret Transform Rule:** Rules → Transform Rules → Modify
  Request Header → create rule, *All incoming requests*, **Set static**,
  header `X-VerifyGH-Origin`, value = a new random secret of 48+ characters
  (for example the output of `python -c "import secrets; print(secrets.token_urlsafe(48))"`).
  Keep it only in Cloudflare and Railway.
* **Webhooks must never be challenged.** Paystack
  (`/api/v1/payments/webhooks/...`) and TextVerified
  (`/api/v1/verification/webhooks/...`) are servers, not browsers: a JS
  challenge or CAPTCHA makes every callback fail. Do not apply challenge rules
  to those paths, and check Security → Events after enabling any bot feature.

### Step 3 - Switch the nameservers, then proxy

1. At the registrar, replace `dns1/dns2.registrar-servers.com` with the two
   nameservers Cloudflare gives you. Propagation can take hours.
2. Keep `www`, `api` and the apex **DNS only** (grey cloud) until Railway's
   domain settings show each custom domain's certificate as issued, then turn
   the proxy on (orange cloud).
3. Check: `curl -sI https://www.getverifygh.com/` shows `server: cloudflare`
   and a `cf-ray` header; sign-in, a deposit and a purchase still work; a
   Paystack test callback and a TextVerified webhook still arrive.

### Step 4 - Turn the origin lock on, in two stages

1. In Railway, on **verifygh, verifygh-worker, verifygh-beat and
   verifygh-web**, set `CLOUDFLARE_ORIGIN_SECRET` to the Transform Rule's value
   and `CLOUDFLARE_MODE=report`. Redeploy.
2. Watch the logs for `request_not_via_cloudflare` for a day. Expected: only
   direct hits on `*.up.railway.app`. Anything on `www`, `api` or the apex means
   the Transform Rule is not applying there - fix it before continuing.
3. Set `CLOUDFLARE_MODE=enforce` on the same services. Direct Railway addresses
   now answer 403 (the old web address still redirects to the real domain
   first).

To undo at any point: `CLOUDFLARE_MODE=off`.

### Step 5 - Turnstile

Create a Turnstile widget for `getverifygh.com` / `www.getverifygh.com`. Put the
**site key** in `NEXT_PUBLIC_TURNSTILE_SITE_KEY` on verifygh-web (public by
design) and the **secret key** in Railway only - never in chat or git. The
server-side verification and which forms require it come with the next change.

## 3. What Cloudflare adds on top of what exists

The application's own controls stay and still apply behind Cloudflare: per-IP
and per-account rate limits on login, registration, password reset, deposits,
OTP, orders and referral checks; purchase caps; abuse flags; referral risk
scoring; refresh-token replay detection. Cloudflare adds DDoS absorption, the
WAF and bot scoring at the edge, and Turnstile for human verification - none of
which the origin can do for itself.
