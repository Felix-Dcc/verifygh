"""Token revocation.

JWTs are self-contained, so "sign out" has to be made true rather than assumed.
Two mechanisms are tested here, because they cover different windows:

* the blacklist revokes one refresh token (sign-out, and rotation replay);
* `token_version` revokes everything at once, including access tokens that are
  already issued and would otherwise stay valid for their full lifetime.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.authentication import issue_tokens, token_version_of

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-1"
LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"


def login(api, user, password=PASSWORD):
    response = api.post(LOGIN, {"email": user.email, "password": password}, format="json")
    assert response.status_code == 200, response.data
    api.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    return response


# ---------------------------------------------------------------------------
# The session-epoch claim
# ---------------------------------------------------------------------------


def test_tokens_carry_the_session_epoch(user):
    access, refresh = issue_tokens(user)
    from rest_framework_simplejwt.tokens import AccessToken

    assert token_version_of(AccessToken(access)) == user.token_version
    assert token_version_of(RefreshToken(refresh)) == user.token_version


def test_a_token_without_the_claim_is_rejected(api, user):
    """Tokens minted before this feature existed must not keep working."""
    refresh = RefreshToken.for_user(user)
    legacy_access = str(refresh.access_token)  # no version claim

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {legacy_access}")
    assert api.get(ME).status_code == 401


def test_bumping_the_epoch_kills_an_issued_access_token(api, user):
    """The gap blacklisting alone cannot close."""
    access, _refresh = issue_tokens(user)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert api.get(ME).status_code == 200

    user.revoke_all_sessions()

    # Same token, same expiry, now refused.
    assert api.get(ME).status_code == 401


def test_bearer_tokens_cannot_skip_the_revocation_check(api, user):
    """A bearer token must be held to the same standard as a cookie."""
    access, _ = issue_tokens(user)
    user.revoke_all_sessions()

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    response = api.get(ME)

    assert response.status_code == 401
    assert response.data["error"]["code"] == "AUTHENTICATION_REQUIRED"


# ---------------------------------------------------------------------------
# Sign-out
# ---------------------------------------------------------------------------


def test_logout_blacklists_the_refresh_token(api, user):
    login(api, user)
    raw_refresh = api.cookies[settings.AUTH_COOKIE_REFRESH].value

    assert api.post("/api/v1/auth/logout/", {}, format="json").status_code == 200

    # The token itself is dead, not merely absent from this browser.
    assert BlacklistedToken.objects.filter(token__token=raw_refresh).exists()

    fresh = type(api)()
    response = fresh.post("/api/v1/auth/refresh/", {"refresh": raw_refresh}, format="json")
    assert response.status_code == 401


def test_logout_succeeds_even_with_a_junk_token(api, user):
    """Ending a session must never fail - that is how people get stuck."""
    login(api, user)
    api.cookies[settings.AUTH_COOKIE_REFRESH] = "not-a-token"

    assert api.post("/api/v1/auth/logout/", {}, format="json").status_code == 200


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_refresh_rotates_and_revokes_the_old_token(api, user):
    login(api, user)
    first = api.cookies[settings.AUTH_COOKIE_REFRESH].value

    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    second = api.cookies[settings.AUTH_COOKIE_REFRESH].value

    assert second != first
    assert BlacklistedToken.objects.filter(token__token=first).exists()


def test_a_replayed_refresh_token_is_refused(api, user):
    """The signal that a refresh token has been stolen."""
    login(api, user)
    stolen = api.cookies[settings.AUTH_COOKIE_REFRESH].value

    api.post("/api/v1/auth/refresh/", {}, format="json")  # victim refreshes

    attacker = type(api)(HTTP_USER_AGENT="Attacker/1.0")
    response = attacker.post("/api/v1/auth/refresh/", {"refresh": stolen}, format="json")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Password change and reset
# ---------------------------------------------------------------------------


def test_password_change_ends_every_other_session(api, user):
    from rest_framework.test import APIClient

    other = APIClient()
    login(other, user)

    changer = APIClient()
    login(changer, user)
    response = changer.post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "Brand-New-Passphrase-7"},
        format="json",
    )
    assert response.status_code == 200

    # The other browser is out.
    assert other.get(ME).status_code == 401
    # The tab that made the change keeps working, on a freshly issued pair.
    assert changer.get(ME).status_code == 200


def test_password_reset_ends_every_session(api, user, monkeypatch):
    from apps.accounts.models import SecurityToken

    captured = {}
    original = SecurityToken.issue

    def spy(cls_user, purpose, ttl_hours, ip=None, **options):
        token, raw = original(cls_user, purpose, ttl_hours, ip, **options)
        captured["raw"] = raw
        return token, raw

    monkeypatch.setattr(SecurityToken, "issue", staticmethod(spy))

    login(api, user)
    assert api.get(ME).status_code == 200

    api.post("/api/v1/auth/password/reset/", {"email": user.email}, format="json")

    from rest_framework.test import APIClient

    anon = APIClient()
    response = anon.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": captured["raw"], "new_password": "Brand-New-Passphrase-7"},
        format="json",
    )
    assert response.status_code == 200

    # Whoever was signed in - including an attacker - is now out.
    assert api.get(ME).status_code == 401


# ---------------------------------------------------------------------------
# Suspension
# ---------------------------------------------------------------------------


def test_suspension_takes_effect_immediately(api, user, admin_user, auth):
    """A suspended user must not keep spending until their token expires."""
    from rest_framework.test import APIClient

    victim = APIClient()
    login(victim, user)
    assert victim.get(ME).status_code == 200

    admin = auth(admin_user, "Correct-Horse-Battery-3")
    response = admin.post(
        f"/api/v1/admin/users/{user.id}/suspend/",
        {"reason": "Confirmed chargeback fraud"},
        format="json",
    )
    assert response.status_code == 200

    # Same access token, now refused - no waiting for expiry.
    assert victim.get(ME).status_code == 401


def test_suspended_user_cannot_refresh(api, user):
    login(api, user)
    raw = api.cookies[settings.AUTH_COOKIE_REFRESH].value

    user.is_suspended = True
    user.save(update_fields=["is_suspended"])

    fresh = type(api)()
    response = fresh.post("/api/v1/auth/refresh/", {"refresh": raw}, format="json")
    assert response.status_code == 403
    assert response.data["error"]["code"] == "ACCOUNT_SUSPENDED"


# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------


def test_issued_refresh_tokens_are_tracked(user):
    """Bulk revocation needs something to enumerate."""
    before = OutstandingToken.objects.filter(user=user).count()
    issue_tokens(user)
    assert OutstandingToken.objects.filter(user=user).count() == before + 1


def test_revoke_all_sessions_blacklists_every_outstanding_token(user):
    issue_tokens(user)
    issue_tokens(user)

    revoked = user.revoke_all_sessions()

    assert revoked >= 2
    outstanding = OutstandingToken.objects.filter(user=user).count()
    blacklisted = BlacklistedToken.objects.filter(token__user=user).count()
    assert blacklisted == outstanding


# ---------------------------------------------------------------------------
# Refresh-token reuse detection
# ---------------------------------------------------------------------------


def _age_blacklist_entry(raw, seconds=120):
    from datetime import timedelta

    from django.utils import timezone

    BlacklistedToken.objects.filter(token__token=raw).update(
        blacklisted_at=timezone.now() - timedelta(seconds=seconds)
    )


def test_replaying_a_rotated_token_ends_every_session(api, user):
    """Two parties hold one credential; we cannot tell which is the thief, so
    both are signed out (RFC 9700 4.14.2)."""
    from apps.audit.models import SuspiciousActivity

    login(api, user)
    stolen = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    api.post("/api/v1/auth/refresh/", {}, format="json")  # victim rotates
    victim_refresh = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    _age_blacklist_entry(stolen)

    attacker = type(api)(HTTP_USER_AGENT="Attacker/1.0")
    assert attacker.post("/api/v1/auth/refresh/", {"refresh": stolen},
                         format="json").status_code == 401

    user.refresh_from_db()
    assert user.token_version == 1
    # The victim's freshly rotated token is dead too - including for the thief,
    # who may have stolen it along with the first.
    assert api.get(ME).status_code == 401
    other = type(api)()
    assert other.post("/api/v1/auth/refresh/", {"refresh": victim_refresh},
                      format="json").status_code == 401
    assert SuspiciousActivity.objects.filter(
        user=user, kind=SuspiciousActivity.Kind.TOKEN_REUSE, level="HIGH"
    ).count() == 1


def test_a_two_tab_race_keeps_both_tabs_signed_in(api, user):
    """Same browser, same token, a second apart: the loser is handed the
    replacement tab one already got, rather than refused."""
    login(api, user)
    shared = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    api.post("/api/v1/auth/refresh/", {}, format="json")  # tab one wins
    replacement = api.cookies[settings.AUTH_COOKIE_REFRESH].value

    tab_two = type(api)()
    response = tab_two.post("/api/v1/auth/refresh/", {"refresh": shared}, format="json")
    assert response.status_code == 200
    assert tab_two.cookies[settings.AUTH_COOKIE_REFRESH].value == replacement
    user.refresh_from_db()
    assert user.token_version == 0
    assert api.get(ME).status_code == 200  # tab one still signed in


def test_another_browser_racing_is_refused_without_a_mass_sign_out(api, user):
    login(api, user)
    shared = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    api.post("/api/v1/auth/refresh/", {}, format="json")

    elsewhere = type(api)(HTTP_USER_AGENT="Other/1.0")
    assert elsewhere.post("/api/v1/auth/refresh/", {"refresh": shared},
                          format="json").status_code == 401
    user.refresh_from_db()
    assert user.token_version == 0  # inside the race grace: no mass sign-out
    assert api.get(ME).status_code == 200


@pytest.mark.parametrize("junk", ["", "not-a-jwt", "a.b.c"])
def test_junk_tokens_never_trigger_a_mass_sign_out(api, user, junk):
    login(api, user)
    type(api)().post("/api/v1/auth/refresh/", {"refresh": junk}, format="json")
    user.refresh_from_db()
    assert user.token_version == 0


def test_a_token_from_a_revoked_epoch_is_not_treated_as_theft(api, user):
    """After a password change old tabs keep sending dead tokens. They are
    already powerless; flagging each one would bury real signals."""
    from apps.audit.models import SuspiciousActivity

    login(api, user)
    old = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    user.revoke_all_sessions()
    _age_blacklist_entry(old)

    type(api)().post("/api/v1/auth/refresh/", {"refresh": old}, format="json")

    user.refresh_from_db()
    assert user.token_version == 1  # unchanged by the replay
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()


def test_only_one_rotation_of_a_token_can_succeed(user):
    """The check-then-blacklist in RefreshView is not atomic by itself; the
    unique blacklist row is what stops two concurrent refreshes both minting."""
    from apps.accounts.authentication import rotate_refresh_token

    _, raw = issue_tokens(user)
    token = RefreshToken(raw)
    assert rotate_refresh_token(token) is True
    assert rotate_refresh_token(token) is False


# ---------------------------------------------------------------------------
# A renewal whose reply was lost (the customer tapped on mid-renewal)
# ---------------------------------------------------------------------------


def _lost_reply(api, user):
    """Rotate, then put the browser back on the token it held before - what a
    browser that never received the renewal's cookies is left with."""
    login(api, user)
    before = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    replacement = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    api.cookies[settings.AUTH_COOKIE_REFRESH] = before
    _age_blacklist_entry(before)  # well past the two-tab race window
    return before, replacement


def test_a_lost_renewal_reply_is_recovered_not_treated_as_theft(api, user):
    """Production, 4 Oct: a renewal took seven seconds on mobile, the customer
    moved on, and every page after presented the retired token until the
    second one was flagged as theft and all their sessions were ended."""
    from apps.audit.models import SuspiciousActivity

    before, replacement = _lost_reply(api, user)

    response = api.post("/api/v1/auth/refresh/", {}, format="json")
    assert response.status_code == 200
    fresh = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert fresh not in (before, replacement)  # a new pair, not the lost one
    assert api.get(ME).status_code == 200
    user.refresh_from_db()
    assert user.token_version == 0
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()

    # And the recovered session renews normally afterwards.
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200


def test_a_retired_token_from_another_browser_is_still_theft(api, user):
    from apps.audit.models import SuspiciousActivity

    before, _ = _lost_reply(api, user)

    thief = type(api)(HTTP_USER_AGENT="Thief/2.0")
    assert thief.post("/api/v1/auth/refresh/", {"refresh": before},
                      format="json").status_code == 401
    user.refresh_from_db()
    assert user.token_version == 1
    assert SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE, level="HIGH").count() == 1


def test_a_replacement_used_by_another_browser_is_caught_at_its_next_renewal(api, user):
    """Another browser renewed with the replacement. The customer, whose
    browser retired the token, keeps the session; the other browser loses its
    copy, and its next renewal is theft."""
    from apps.audit.models import SuspiciousActivity

    before, replacement = _lost_reply(api, user)
    other = type(api)(HTTP_USER_AGENT="Other/1.0")
    assert other.post("/api/v1/auth/refresh/", {"refresh": replacement},
                      format="json").status_code == 200
    others = other.cookies[settings.AUTH_COOKIE_REFRESH].value
    _age_blacklist_entry(replacement)

    assert api.post("/api/v1/auth/refresh/", {"refresh": before},
                    format="json").status_code == 200
    assert api.get(ME).status_code == 200

    _age_blacklist_entry(others)
    assert other.post("/api/v1/auth/refresh/", {}, format="json").status_code == 401
    user.refresh_from_db()
    assert user.token_version == 1
    assert SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE, level="HIGH").count() == 1


def test_the_same_browser_with_a_token_recovery_revoked_is_recovered(api, user):
    """Production, 6 Oct: an iPhone renewed at 18:24, came back with the
    older token at 18:25 (recovered, which revoked the 18:24 one), then at
    18:53 presented the 18:24 token after all - and was flagged as theft."""
    from apps.audit.models import SuspiciousActivity

    before, replacement = _lost_reply(api, user)
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200  # 18:25
    api.cookies[settings.AUTH_COOKIE_REFRESH] = replacement  # 18:53: the other copy
    _age_blacklist_entry(replacement, seconds=28 * 60)

    response = api.post("/api/v1/auth/refresh/", {}, format="json")
    assert response.status_code == 200
    assert api.get(ME).status_code == 200
    user.refresh_from_db()
    assert user.token_version == 0
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200


def test_the_same_browser_behind_its_own_renewals_is_recovered(api, user):
    """Production, 7 Oct: an iPhone renewed through the night, then at 04:04
    presented a token it had already renewed past."""
    from apps.audit.models import SuspiciousActivity

    login(api, user)
    oldest = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    middle = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    latest = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    _age_blacklist_entry(oldest, seconds=3600)
    _age_blacklist_entry(middle, seconds=1800)
    api.cookies[settings.AUTH_COOKIE_REFRESH] = oldest

    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    assert api.cookies[settings.AUTH_COOKIE_REFRESH].value not in (oldest, middle, latest)
    assert api.get(ME).status_code == 200
    user.refresh_from_db()
    assert user.token_version == 0
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()

    # The copy it had moved on to was revoked, and leads back to the live session.
    api.cookies[settings.AUTH_COOKIE_REFRESH] = latest
    _age_blacklist_entry(latest)
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200


def test_a_browser_that_already_renewed_on_inside_the_race_window_is_refused_quietly(
        api, user):
    from apps.audit.models import SuspiciousActivity

    login(api, user)
    oldest = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    api.post("/api/v1/auth/refresh/", {}, format="json")
    api.post("/api/v1/auth/refresh/", {}, format="json")
    stale = type(api)()
    assert stale.post("/api/v1/auth/refresh/", {"refresh": oldest},
                      format="json").status_code == 401
    user.refresh_from_db()
    assert user.token_version == 0
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()


def test_recovery_ends_with_its_window(api, user):
    from django.core.cache import cache

    _lost_reply(api, user)
    cache.clear()  # the rotation note has expired

    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 401
    user.refresh_from_db()
    assert user.token_version == 1


def test_coming_back_later_on_another_network_is_still_recovered(api, user):
    """Production, 5 Oct: the reply was lost at 20:26 and the customer came
    back at 21:07 - after a 10-minute window, and on a phone whose address had
    changed. Same browser, replacement never used: still them."""
    from apps.audit.models import SuspiciousActivity

    before, replacement = _lost_reply(api, user)
    _age_blacklist_entry(before, seconds=41 * 60)

    response = api.post("/api/v1/auth/refresh/", {}, format="json",
                        REMOTE_ADDR="203.0.113.77")
    assert response.status_code == 200
    assert api.cookies[settings.AUTH_COOKIE_REFRESH].value not in (before, replacement)
    assert api.get(ME).status_code == 200
    user.refresh_from_db()
    assert user.token_version == 0
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()


def test_a_thief_with_the_same_browser_is_caught_within_the_daily_limit(api, user):
    """The thief renews first. Each recovery takes the session from whoever
    held it and hands the other a new one, so a thief on an identical browser
    and the customer take turns - only so many times a day before it is theft.
    Both clients send the same (empty) user agent: the exact-browser limit."""
    from apps.accounts.authentication import (
        ROTATION_RECOVERY_EXACT_DAILY_LIMIT as ROTATION_RECOVERY_DAILY_LIMIT,
    )
    from apps.audit.models import SuspiciousActivity

    login(api, user)
    stolen = api.cookies[settings.AUTH_COOKIE_REFRESH].value
    thief = type(api)()  # identical browser
    assert thief.post("/api/v1/auth/refresh/", {"refresh": stolen},
                      format="json").status_code == 200   # thief renews first
    _age_blacklist_entry(stolen)

    turns = [api, thief]
    for turn in range(ROTATION_RECOVERY_DAILY_LIMIT + 1):
        client = turns[turn % 2]
        status = client.post("/api/v1/auth/refresh/", {}, format="json").status_code
        _age_blacklist_entry(client.cookies[settings.AUTH_COOKIE_REFRESH].value)
        for other in turns:
            _age_blacklist_entry(other.cookies[settings.AUTH_COOKIE_REFRESH].value)
        if turn < ROTATION_RECOVERY_DAILY_LIMIT:
            assert status == 200, turn
        else:
            assert status == 401

    user.refresh_from_db()
    assert user.token_version == 1
    assert SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE, level="HIGH").exists()


SAFARI_26_4 = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
               "(KHTML, like Gecko) Version/26.4 Mobile/15E148 Safari/604.1")
SAFARI_26_6 = SAFARI_26_4.replace("Version/26.4", "Version/26.6").replace("18_7", "18_8")
CHROME_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) CriOS/152.0.7977.64 Mobile/15E148 Safari/604.1")


def test_a_browser_that_updated_since_its_last_renewal_is_still_recovered(api, user):
    """Production, 8 Oct: an iPhone came back a week later with Safari updated,
    and its own session was flagged as theft."""
    from apps.audit.models import SuspiciousActivity

    phone = type(api)(HTTP_USER_AGENT=SAFARI_26_4)
    login(phone, user)
    before = phone.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert phone.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    phone.cookies[settings.AUTH_COOKIE_REFRESH] = before  # the renewal's reply was lost
    _age_blacklist_entry(before, seconds=7 * 24 * 3600)

    updated = type(api)(HTTP_USER_AGENT=SAFARI_26_6)
    updated.cookies[settings.AUTH_COOKIE_REFRESH] = before
    assert updated.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.token_version == 0
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()


def test_another_browser_on_the_same_phone_is_still_theft(api, user):
    from apps.audit.models import SuspiciousActivity

    phone = type(api)(HTTP_USER_AGENT=SAFARI_26_4)
    login(phone, user)
    before = phone.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert phone.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    _age_blacklist_entry(before)

    other = type(api)(HTTP_USER_AGENT=CHROME_IOS)
    assert other.post("/api/v1/auth/refresh/", {"refresh": before},
                      format="json").status_code == 401
    user.refresh_from_db()
    assert user.token_version == 1
    assert SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE, level="HIGH").exists()


def test_a_session_noted_before_the_change_is_still_recovered(api, user):
    """Notes written before 8 Oct hold the full user agent's hash."""
    import hashlib

    from django.core.cache import cache
    from rest_framework_simplejwt.settings import api_settings
    from rest_framework_simplejwt.state import token_backend

    phone = type(api)(HTTP_USER_AGENT=SAFARI_26_4)
    login(phone, user)
    before = phone.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert phone.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    jti = token_backend.decode(before, verify=True)[api_settings.JTI_CLAIM]
    key = f"refresh-rotated:{jti}"
    note = cache.get(key)
    note["client"] = hashlib.sha256(SAFARI_26_4.encode()).hexdigest()  # the old scheme
    cache.set(key, note, 3600)
    phone.cookies[settings.AUTH_COOKIE_REFRESH] = before
    _age_blacklist_entry(before)

    assert phone.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.token_version == 0


def _lose_a_renewal(phone, seconds=3600):
    """Renew, then put the old cookie back as if the reply never arrived."""
    before = phone.cookies[settings.AUTH_COOKIE_REFRESH].value
    assert phone.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200
    phone.cookies[settings.AUTH_COOKIE_REFRESH] = before
    _age_blacklist_entry(before, seconds=seconds)
    return before


def test_the_exact_same_iphone_is_recovered_more_than_three_times_a_day(api, user):
    """Production, 9 Oct: an iPhone lost a fourth renewal by 09:22 and was signed
    out as stolen, then signed straight back in with its password."""
    from apps.accounts.authentication import ROTATION_RECOVERY_DAILY_LIMIT
    from apps.audit.models import SuspiciousActivity

    phone = type(api)(HTTP_USER_AGENT=SAFARI_26_4)
    login(phone, user)
    for _ in range(ROTATION_RECOVERY_DAILY_LIMIT + 3):
        _lose_a_renewal(phone)
        assert phone.post("/api/v1/auth/refresh/", {}, format="json").status_code == 200

    user.refresh_from_db()
    assert user.token_version == 0
    assert not SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE).exists()


def test_a_merely_similar_browser_keeps_the_stricter_limit(api, user):
    """Same kind of browser, different version: three a day, as before."""
    from django.core.cache import cache

    from apps.accounts.authentication import ROTATION_RECOVERY_DAILY_LIMIT
    from apps.audit.models import SuspiciousActivity

    phone = type(api)(HTTP_USER_AGENT=SAFARI_26_4)
    login(phone, user)
    before = _lose_a_renewal(phone)
    cache.set(f"refresh-recoveries:{user.pk}", ROTATION_RECOVERY_DAILY_LIMIT, 24 * 3600)

    similar = type(api)(HTTP_USER_AGENT=SAFARI_26_6)
    similar.cookies[settings.AUTH_COOKIE_REFRESH] = before
    assert similar.post("/api/v1/auth/refresh/", {}, format="json").status_code == 401
    assert SuspiciousActivity.objects.filter(
        kind=SuspiciousActivity.Kind.TOKEN_REUSE, level="HIGH").exists()


def test_the_exact_browser_is_still_caught_past_its_own_limit(api, user):
    from django.core.cache import cache

    from apps.accounts.authentication import ROTATION_RECOVERY_EXACT_DAILY_LIMIT

    phone = type(api)(HTTP_USER_AGENT=SAFARI_26_4)
    login(phone, user)
    _lose_a_renewal(phone)
    cache.set(f"refresh-recoveries:{user.pk}", ROTATION_RECOVERY_EXACT_DAILY_LIMIT, 24 * 3600)
    assert phone.post("/api/v1/auth/refresh/", {}, format="json").status_code == 401
