# Sign in with Google

"Continue with Google" on /login and "Sign up with Google" on /register. The
buttons appear only once the API has a Google OAuth client. Until then
`GET /api/v1/auth/sign-in-options/` answers `{"google": false}` and the pages
show the email form alone.

## How it works

1. The button links to `GET /api/v1/auth/google/start/`. The API creates a
   `state`, a `nonce` and a PKCE verifier. It keeps them in a signed, HttpOnly
   cookie scoped to the callback path, valid for 10 minutes, and sends the
   browser to Google's account chooser.
2. Google returns the browser to `GET /api/v1/auth/google/callback/` with a
   one-time code. The API checks `state` against the cookie, then exchanges the
   code with the client secret and the PKCE verifier. Google answers with an
   ID token.
3. The ID token's issuer, audience, expiry, nonce and `email_verified` are
   checked. The account is found in this order:
   * the account already linked to that Google account (`sub`);
   * otherwise the account with that email address, which is linked now;
   * otherwise a new account, created with its email already verified.
4. The API sets the usual session cookies and sends the browser to the app.
   Staff go to `/admin`. If anything fails, the browser goes back to the form
   with `?google=<reason>`, and the page explains it.

The client secret, codes and tokens are never logged or sent to the browser.
Nothing from Google runs on our pages, so the Content-Security-Policy is
unchanged.

### Rules worth knowing

* **Terms.** "Sign up with Google" requires the terms box to be ticked, and the
  new account records the acceptance. A new account made from the **sign-in**
  page has not accepted the terms. The app asks for them before any purchase,
  as it does when the terms change.
* **Referrals.** An invite code on /register carries through Google sign-up.
  The account is verified from the start, so the referral is checked straight
  away.
* **Unverified accounts.** If someone registered the address with a password
  but never verified it, signing in with Google links that account, retires the
  password and ends its sessions. That password was set by someone who never
  proved they own the address. The owner can set a new one with "Forgot
  password?".
* **Google-only accounts** have no password. The Account page offers "Set a
  password", which sends a reset link.

## Setting it up

You do this; nobody else needs the secret.

1. **Google Cloud Console → APIs & Services → OAuth consent screen.** User type
   *External*. App name *VerifyGH*, support email, the logo, and links to
   https://www.getverifygh.com/privacy and /terms. Scopes: `openid`, `email`
   and `profile` only. These need no Google verification review. Publish the
   app ("In production"); while it is in *Testing*, only listed test users can
   sign in.
2. **Credentials → Create credentials → OAuth client ID**, type *Web
   application*.
   * Authorised JavaScript origins: none needed.
   * Authorised redirect URIs:
     `https://api.getverifygh.com/api/v1/auth/google/callback/` (and
     `http://localhost:8000/api/v1/auth/google/callback/` for local work).
3. In **Railway → verifygh** (the API): set `GOOGLE_OAUTH_CLIENT_ID` and
   `GOOGLE_OAUTH_CLIENT_SECRET`. `GOOGLE_OAUTH_REDIRECT_URI` is already set by
   `.railway/railway.ts`. If you set variables by hand instead, set it to the
   redirect URI above. Redeploy the API. The frontend needs nothing.

Production refuses to boot with only one of the two set, or with a redirect
URI that is not `https://`. To switch Google sign-in off, clear both.
