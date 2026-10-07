# Pausing VerifyGH

Why this exists: on 6 Oct 2026 the number provider stopped handing out
numbers, and every order was charged, failed twenty seconds later and was
refunded. Pausing stops customers *before* they pay.

There are two ways to pause, for two kinds of emergency:

| Situation | Use | Covers |
| --- | --- | --- |
| The site works, something upstream doesn't (provider down, payments delayed) | **Pause site** button in the admin | New orders, and optionally new top-ups |
| The site itself is down, or you cannot reach the admin | **Cloudflare maintenance page** (below) | The whole customer site on www |

---

## 1. The "Pause site" button (everyday)

**Where:** the red **Pause** / **Pause site** button at the top of every admin
page. Admins and super admins have it (`MAINTENANCE_MANAGE`).

**How:** tap it, pick what to pause, tap a reason, optionally tap when you
expect to be back, then **Pause now**. Two taps from any admin page.

* **Pause buying** - no new orders or number reuse. Top-ups stay open.
* **Pause buying and top-ups** - no new deposits either.

**What customers see:** a notice at the top of every page ("Buying numbers is
paused for a short while. Your balance is safe and nothing will be
charged..."), the buy dialog says so before they tap Buy, and with the second
level the deposit page says top-ups are paused. Provider names and reasons are
never shown to customers.

**What keeps working - always:** orders already waiting for their code (they
finish, or are refunded automatically), deposits a customer is already
approving on their phone (PIN prompt or Telecel code), Paystack and TextVerified
webhooks, refunds and the background jobs, signing in, wallets and history,
and the whole admin.

**Reopening:** tap **Turn off** on the red strip that shows on every admin page
while the site is paused. One tap, no questions. The site **never reopens by
itself** - "expected back" is only what customers are told.

Every pause, change and reopen is in **Admin > System > Admin actions** with who
did it and why, and staff get a notification and an email.

Code: `backend/apps/common/maintenance.py`, `frontend/src/components/maintenance.tsx`.

---

## 2. Cloudflare maintenance page (when the site itself is down)

This works even when Railway is down, because Cloudflare answers before the
request reaches our servers. **Set it up in advance, while things are calm** -
an emergency is the wrong time to build a rule. Check each step against the
Cloudflare dashboard as you go; menus move.

### Set up once

1. **A maintenance page that does not live on Railway.** Create a Cloudflare
   Pages project with a single `index.html` ("VerifyGH is down for maintenance.
   Your balance is safe. We'll be back shortly.") and give it its own address,
   for example `maintenance.getverifygh.com`.
   Docs: https://developers.cloudflare.com/pages/
2. **A redirect rule, saved switched off.** getverifygh.com > Rules > Redirect
   Rules > Create rule (Single Redirects).
   Docs: https://developers.cloudflare.com/rules/url-forwarding/single-redirects/
   * Name: `Maintenance page`
   * Custom filter expression:
     `http.host eq "www.getverifygh.com" and not starts_with(http.request.uri.path, "/admin")`
   * Then: Static redirect to `https://maintenance.getverifygh.com/`,
     status **302** (temporary). Never 301: browsers remember a 301 and would
     keep sending customers to the maintenance page after it is switched off.
   * Deploy it, then switch it **off** in the rules list. Confirm the rules list
     shows an on/off control for it; if it does not, note how to disable it here.
3. **Rehearse once.** Switch it on, open www.getverifygh.com on your phone (you
   should land on the maintenance page), open www.getverifygh.com/admin (it
   should not redirect), switch it off, check the site is back.

### In an emergency

Cloudflare app or dashboard > getverifygh.com > Rules > Redirect Rules >
switch **Maintenance page** on. Switch it off the same way when the site is
back.

### Rules for this rule

* **Only `www.getverifygh.com`. Never `api.getverifygh.com`.** Paystack and
  TextVerified send their webhooks to the API; redirecting or blocking them
  means customers' payments are not credited. See `docs/CLOUDFLARE.md`.
* **Keep `/admin` out of it**, so the admin (and its Pause button) still works
  whenever the servers do.
* **302, not 301.**

---

## Never

* Never block, challenge or redirect `api.getverifygh.com` or the webhook paths.
* Never switch off the Cloudflare origin lock (`CLOUDFLARE_MODE`), the origin
  secret or the sign-in check (Turnstile) to get into the admin faster.
* Never stop the Celery worker or beat to "pause" the site: they refund orders
  and expire unpaid deposits.
* Never put secrets in links, chat or `NEXT_PUBLIC_*` variables.
