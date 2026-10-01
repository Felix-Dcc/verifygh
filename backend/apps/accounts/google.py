"""Sign in with Google: OpenID Connect's authorisation-code flow, server side.

The browser is sent to Google, Google sends it back to our callback with a
one-time code, and this server exchanges that code - with the client secret and
the PKCE verifier only it holds - for an ID token naming the Google account.
Nothing from Google runs on our pages, so the site's Content-Security-Policy
needs no exception for it.

The ID token arrives straight from Google's token endpoint over TLS, in reply to
a request authenticated with our client secret. OpenID Connect Core 3.1.3.7
allows TLS to stand in for the token's signature in exactly that case; every
claim that matters - issuer, audience, expiry, our nonce, a verified email - is
still checked here.

The client secret, codes and tokens are never logged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from django.conf import settings

logger = logging.getLogger("verifygh.auth")

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

#: How far our clock may drift from Google's before a fresh token looks expired.
CLOCK_SKEW_SECONDS = 120


class GoogleSignInError(Exception):
    """Sign-in with Google did not complete. `reason` is a short code for the UI."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str


def is_configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def new_pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge), per RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(*, state: str, nonce: str, code_challenge: str) -> str:
    query = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Always offer the account chooser, so a shared computer does not
        # silently sign in as whoever used Google on it last.
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def exchange_code(code: str, *, code_verifier: str, nonce: str) -> GoogleIdentity:
    """Trade the callback's code for the identity of the Google account behind it."""
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=10,
        )
    except requests.RequestException:
        logger.warning("google_token_exchange_unreachable")
        raise GoogleSignInError("unavailable") from None

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200 or not isinstance(payload, dict):
        # Google's error code ("invalid_grant", ...) names the problem without
        # repeating anything we sent.
        error = payload.get("error") if isinstance(payload, dict) else None
        logger.warning(
            "google_token_exchange_failed",
            extra={"status": response.status_code, "error": str(error or "")[:60]},
        )
        raise GoogleSignInError("failed")

    return _identity(payload.get("id_token"), nonce=nonce)


def _identity(id_token, *, nonce: str) -> GoogleIdentity:
    claims = _claims(id_token)

    if claims.get("iss") not in ISSUERS:
        _invalid("issuer")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if settings.GOOGLE_OAUTH_CLIENT_ID not in audiences:
        _invalid("audience")
    if len(audiences) > 1 and claims.get("azp") != settings.GOOGLE_OAUTH_CLIENT_ID:
        _invalid("authorized_party")
    expires = claims.get("exp")
    if not isinstance(expires, int | float) or expires + CLOCK_SKEW_SECONDS < time.time():
        _invalid("expired")
    if not nonce or not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
        _invalid("nonce")

    subject = str(claims.get("sub") or "")
    email = str(claims.get("email") or "").strip().lower()
    if not subject or len(subject) > 255 or "@" not in email or len(email) > 254:
        _invalid("claims")
    # Only an address Google has confirmed belongs to this account may sign in
    # to the VerifyGH account with that address.
    if claims.get("email_verified") not in (True, "true"):
        raise GoogleSignInError("unverified")

    name = str(claims.get("name") or "").strip()[:150]
    return GoogleIdentity(subject=subject, email=email, name=name)


def _claims(id_token) -> dict:
    if not isinstance(id_token, str) or id_token.count(".") != 2:
        _invalid("malformed")
    body = id_token.split(".")[1]
    try:
        decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        claims = json.loads(decoded)
    except (binascii.Error, ValueError):
        _invalid("malformed")
    if not isinstance(claims, dict):
        _invalid("malformed")
    return claims


def _invalid(check: str):
    logger.warning("google_id_token_rejected", extra={"check": check})
    raise GoogleSignInError("failed")
