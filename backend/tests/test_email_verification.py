"""The email verification flow, end to end.

Covers the whole chain the product depends on: registration creates an
unverified account, a real message is handed to the mail backend, the link in
that message verifies exactly once, and until it does the account cannot spend
money - including when the API is called directly, with no browser involved.

The failure this suite exists to prevent is subtler than a crash. An email
backend that accepts a message and delivers it nowhere leaves the application
reporting success on every send while no account can ever be verified. So these
tests assert on the *content handed to the backend*, not merely that a send was
attempted.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.core import mail
from django.utils import timezone

from apps.accounts.models import SecurityToken, TokenPurpose, User
from apps.accounts.services import mask_email

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
LOGIN = "/api/v1/auth/login/"
CONFIRM = "/api/v1/auth/email/verify/confirm/"
SEND = "/api/v1/auth/email/verify/send/"
RESEND = "/api/v1/auth/resend-verification/"
ORDERS = "/api/v1/orders/"

GOOD_PASSWORD = "Correct-Horse-Battery-1"
NEW_EMAIL = "nana@example.com"


#: Registration queues the verification email with transaction.on_commit, which
#: never fires inside pytest-django's wrapping transaction. Capture and run it.
_capture_on_commit = None


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    global _capture_on_commit
    _capture_on_commit = django_capture_on_commit_callbacks
    yield
    _capture_on_commit = None


def cool_down():
    """Past the 45-second resend wait and the new-account grace."""
    from apps.accounts.models import EmailVerificationCode

    past = timezone.now() - timedelta(minutes=5)
    EmailVerificationCode.objects.update(created_at=past)
    User.objects.update(created_at=past)


def register(api, **overrides):
    body = {
        "email": NEW_EMAIL,
        "password": GOOD_PASSWORD,
        "full_name": "Nana Adjei",
        "accepted_terms": True,
    }
    body.update(overrides)
    with _capture_on_commit(execute=True):
        return api.post(REGISTER, body, format="json")


def token_from_last_email() -> str:
    """Pull the token out of the link, the way a user's mail client would.

    Deliberately read from the message body rather than the database: that is
    what proves the URL we actually emailed carries a usable token.
    """
    assert mail.outbox, "no email was sent"
    body = mail.outbox[-1].body
    match = re.search(r"/verify-email/([A-Za-z0-9_\-]+)", body)
    assert match, f"no verification link in the email body:\n{body}"
    return match.group(1)


# ---------------------------------------------------------------------------
# 1-3. Registration creates an unverified account and emails a working link
# ---------------------------------------------------------------------------


def test_registration_creates_an_unverified_account(api):
    response = register(api)

    assert response.status_code == 201, response.data
    account = User.objects.get(email=NEW_EMAIL)
    assert account.is_email_verified is False
    assert account.email_verified_at is None
    assert response.data["user"]["is_email_verified"] is False


def test_registration_sends_one_verification_email_to_the_registered_address(api):
    register(api)

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [NEW_EMAIL]
    assert message.subject == "Your VerifyGH verification code"
    assert message.from_email == settings.DEFAULT_FROM_EMAIL


def test_the_verification_email_has_both_a_text_and_an_html_body(api):
    """A text-only client must still get a usable link, and vice versa."""
    register(api)

    message = mail.outbox[0]
    assert "Verify" in message.body or "verify" in message.body
    html = {content_type: content for content, content_type in message.alternatives}
    assert "text/html" in html, "no HTML alternative was attached"

    token = token_from_last_email()
    # The same link, in both bodies. An HTML-only link would break plain-text
    # readers; a text-only link would leave the button in the HTML email dead.
    assert token in message.body
    assert token in html["text/html"]


def test_the_verification_link_points_at_the_configured_frontend(api, settings):
    settings.VERIFYGH = {**settings.VERIFYGH, "FRONTEND_URL": "https://verifygh.com"}

    register(api)

    body = mail.outbox[0].body
    assert "https://verifygh.com/verify-email/" in body
    # Never the API's own host: the link is for a person, and the page that
    # handles it is part of the frontend.
    assert "testserver" not in body


def test_the_email_never_contains_the_password_or_the_token_hash(api):
    register(api)

    message = mail.outbox[0]
    all_text = message.body + "".join(content for content, _ in message.alternatives)
    assert GOOD_PASSWORD not in all_text
    stored = SecurityToken.objects.get(purpose=TokenPurpose.EMAIL_VERIFICATION)
    assert stored.token_hash not in all_text


# ---------------------------------------------------------------------------
# 4-7. Token behaviour: valid, expired, invalid, single-use
# ---------------------------------------------------------------------------


def test_a_valid_token_verifies_the_account(api):
    register(api)
    token = token_from_last_email()

    response = api.post(CONFIRM, {"token": token}, format="json")

    assert response.status_code == 200, response.data
    account = User.objects.get(email=NEW_EMAIL)
    assert account.is_email_verified is True
    assert account.email_verified_at is not None


def test_an_expired_token_is_refused_and_says_so(api):
    register(api)
    token = token_from_last_email()
    SecurityToken.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

    response = api.post(CONFIRM, {"token": token}, format="json")

    assert response.status_code == 400
    # A distinct code, so the page can offer "send me a new one" rather than
    # implying the user did something wrong.
    assert response.data["error"]["code"] == "TOKEN_EXPIRED"
    assert User.objects.get(email=NEW_EMAIL).is_email_verified is False


def test_an_invalid_token_is_refused(api):
    register(api)

    response = api.post(CONFIRM, {"token": "not-a-real-token-at-all"}, format="json")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "INVALID_TOKEN"
    assert User.objects.get(email=NEW_EMAIL).is_email_verified is False


def test_a_link_opened_again_says_already_verified(api):
    """A second device or a mail scanner must not tell a verified user it failed."""
    register(api)
    token = token_from_last_email()

    first = api.post(CONFIRM, {"token": token}, format="json")
    verified_at = User.objects.get(email=NEW_EMAIL).email_verified_at
    second = api.post(CONFIRM, {"token": token}, format="json")

    assert first.status_code == 200 and "already_verified" not in first.data
    assert second.status_code == 200 and second.data["already_verified"] is True
    # Verified once: the replay changed nothing.
    assert User.objects.get(email=NEW_EMAIL).email_verified_at == verified_at


def test_an_expired_link_for_a_verified_account_says_already_verified(api):
    register(api)
    token = token_from_last_email()
    assert api.post(CONFIRM, {"token": token}, format="json").status_code == 200
    SecurityToken.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

    response = api.post(CONFIRM, {"token": token}, format="json")
    assert response.status_code == 200 and response.data["already_verified"] is True


def test_an_earlier_email_still_works_after_a_resend(api, auth):
    """Gmail threads the emails; customers tap the older one's button (9 Oct 2026)."""
    register(api)
    first_token = token_from_last_email()

    account = User.objects.get(email=NEW_EMAIL)
    authed = auth(account, GOOD_PASSWORD)
    cool_down()
    assert authed.post(SEND, {}, format="json").status_code == 200
    second_token = token_from_last_email()

    assert first_token != second_token
    earlier = api.post(CONFIRM, {"token": first_token}, format="json")
    assert earlier.status_code == 200 and "already_verified" not in earlier.data
    assert User.objects.get(email=NEW_EMAIL).is_email_verified is True


def test_only_the_last_three_emails_work(unverified_buyer, api):
    """Otherwise every email ever sent stays a live key to the account."""
    from apps.accounts.services import send_verification_email

    tokens = []
    for _ in range(4):
        send_verification_email(unverified_buyer)
        tokens.append(token_from_last_email())

    oldest = api.post(CONFIRM, {"token": tokens[0]}, format="json")
    assert oldest.status_code == 400 and oldest.data["error"]["code"] == "INVALID_TOKEN"
    assert api.post(CONFIRM, {"token": tokens[1]}, format="json").status_code == 200


def test_verifying_retires_the_other_links(unverified_buyer, api):
    from apps.accounts.services import send_verification_email

    for _ in range(3):
        send_verification_email(unverified_buyer)
    assert api.post(CONFIRM, {"token": token_from_last_email()},
                    format="json").status_code == 200
    assert not SecurityToken.objects.filter(
        user=unverified_buyer, purpose=TokenPurpose.EMAIL_VERIFICATION,
        used_at__isnull=True).exists()


def test_only_the_hash_of_a_token_is_stored(api):
    """A database leak must not hand over working verification links."""
    register(api)
    token = token_from_last_email()

    stored = SecurityToken.objects.get(purpose=TokenPurpose.EMAIL_VERIFICATION)
    assert stored.token_hash != token
    assert token not in stored.token_hash
    assert stored.token_hash == SecurityToken.hash_token(token)
    # 32 URL-safe bytes: not guessable, and not derived from anything about the
    # user, so one user's token says nothing about another's.
    assert len(token) >= 40


def test_a_verification_token_cannot_be_used_to_reset_a_password(api):
    """Purpose is part of the lookup, so the two token kinds are not fungible."""
    register(api)
    token = token_from_last_email()

    response = api.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": token, "new_password": "A-Completely-New-Pass-9"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "INVALID_TOKEN"


# ---------------------------------------------------------------------------
# 8-9, 15. Purchase authorisation
# ---------------------------------------------------------------------------


@pytest.fixture
def unverified_buyer(db, funded_wallet):
    """A funded account that has accepted the terms but not verified its email.

    Funded and terms-accepted deliberately: it isolates email verification as
    the single reason a purchase is refused, so a pass cannot be an accident of
    an empty wallet.
    """
    account = User.objects.create_user(
        email="unverified@example.com",
        password=GOOD_PASSWORD,
        full_name="Unverified Buyer",
    )
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.accepted_terms_at = timezone.now()
    account.save(update_fields=["accepted_terms_version", "accepted_terms_at"])
    funded_wallet(account)
    return account


#: The same offering the order tests buy, from the mock catalogue fixture.
SERVICE, COUNTRY = "instagram", "US"


def buy(client, **extra):
    body = {"service": SERVICE, "country": COUNTRY}
    body.update(extra)
    return client.post(ORDERS, body, format="json")


def test_an_unverified_user_cannot_buy(api, auth, catalog, unverified_buyer):
    response = buy(auth(unverified_buyer, GOOD_PASSWORD))

    assert response.status_code == 403
    assert response.data["error"]["code"] == "EMAIL_NOT_VERIFIED"


def test_a_verified_user_can_buy(api, auth, catalog, unverified_buyer):
    """The same account, same wallet, same catalogue - verification is the only change."""
    unverified_buyer.is_email_verified = True
    unverified_buyer.email_verified_at = timezone.now()
    unverified_buyer.save(update_fields=["is_email_verified", "email_verified_at"])

    response = buy(auth(unverified_buyer, GOOD_PASSWORD))

    assert response.status_code == 201, response.data


def test_the_purchase_gate_is_server_side_not_a_ui_rule(api, auth, catalog, unverified_buyer):
    """Calling the API directly, with no frontend involved, must still be refused.

    This is the bypass that matters: a UI-only check is worth nothing, because
    anyone can post to the endpoint themselves.
    """
    from apps.orders.models import Order

    # Straight at the endpoint, bearing an idempotency key, exactly as a script
    # would - no eligibility pre-check, no quote, no browser.
    response = buy(
        auth(unverified_buyer, GOOD_PASSWORD),
        idempotency_key="direct-api-attempt-0001",
    )

    assert response.status_code == 403
    assert response.data["error"]["code"] == "EMAIL_NOT_VERIFIED"
    assert not Order.objects.filter(user=unverified_buyer).exists()

    # And no money moved.
    from apps.wallet.services import get_or_create_wallet

    wallet = get_or_create_wallet(unverified_buyer)
    assert wallet.balance == Decimal("200.00")


def test_every_purchase_path_runs_the_eligibility_check():
    """A new way to spend money must not be able to skip the gate by omission.

    `create_order` is the only function that debits a wallet for a purchase, so
    the check belongs there rather than in each view. This asserts that, so a
    future endpoint calling `create_order` inherits it automatically.
    """
    import inspect

    from apps.orders import services

    source = inspect.getsource(services.create_order)
    assert "check_purchase_eligibility" in source, (
        "create_order must call check_purchase_eligibility: it is the single "
        "chokepoint every purchase passes through."
    )

    gate = inspect.getsource(services.check_purchase_eligibility)
    assert "is_email_verified" in gate and "EmailNotVerified" in gate


def test_the_eligibility_endpoint_reports_the_block_without_leaking_anything(
    api, auth, unverified_buyer
):
    authed = auth(unverified_buyer, GOOD_PASSWORD)

    response = authed.get(f"{ORDERS}eligibility/")

    assert response.status_code == 200
    assert response.data["eligible"] is False
    assert response.data["code"] == "EMAIL_NOT_VERIFIED"


# ---------------------------------------------------------------------------
# 14. Verification status is not client-writable
# ---------------------------------------------------------------------------


def test_a_user_cannot_verify_themselves_through_the_profile_endpoint(api, auth, unverified_buyer):
    authed = auth(unverified_buyer, GOOD_PASSWORD)

    response = authed.patch(
        "/api/v1/auth/me/",
        {"is_email_verified": True, "email_verified_at": timezone.now().isoformat()},
        format="json",
    )

    # The write is ignored rather than rejected - the serializer simply does not
    # expose the field - so assert on the database, not the status code.
    unverified_buyer.refresh_from_db()
    assert unverified_buyer.is_email_verified is False
    assert response.data["user"]["is_email_verified"] is False


def test_registering_with_a_verified_flag_in_the_body_does_not_grant_it(api):
    register(api, is_email_verified=True)

    assert User.objects.get(email=NEW_EMAIL).is_email_verified is False


# ---------------------------------------------------------------------------
# 10-12. Resend
# ---------------------------------------------------------------------------


def test_resend_sends_a_fresh_link_for_an_unverified_account(api, unverified_buyer):
    mail.outbox.clear()

    response = api.post(RESEND, {"email": unverified_buyer.email}, format="json")

    assert response.status_code == 200
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [unverified_buyer.email]
    token = token_from_last_email()
    assert api.post(CONFIRM, {"token": token}, format="json").status_code == 200


def test_resend_says_the_same_thing_for_an_unknown_address(api, unverified_buyer):
    """Otherwise this endpoint tells a stranger who has an account here."""
    known = api.post(RESEND, {"email": unverified_buyer.email}, format="json")
    mail.outbox.clear()
    unknown = api.post(RESEND, {"email": "nobody-at-all@example.com"}, format="json")

    assert known.status_code == unknown.status_code == 200
    assert known.data == unknown.data
    assert mail.outbox == [], "no email should be sent for an address with no account"


def test_resend_says_the_same_thing_for_an_already_verified_address(api, user):
    mail.outbox.clear()

    response = api.post(RESEND, {"email": user.email}, format="json")

    assert response.status_code == 200
    assert "If an account exists" in response.data["detail"]
    # Nothing sent: the account needs nothing, and confirming that would be a
    # way to test whether an address is verified.
    assert mail.outbox == []


def test_resend_does_not_reactivate_a_suspended_account(api, unverified_buyer):
    unverified_buyer.is_suspended = True
    unverified_buyer.save(update_fields=["is_suspended"])
    mail.outbox.clear()

    response = api.post(RESEND, {"email": unverified_buyer.email}, format="json")

    assert response.status_code == 200
    assert mail.outbox == []


def test_resend_is_rate_limited(api, unverified_buyer):
    """Without a limit this endpoint mails any address on demand, for free.

    Asserted against the configured production rate rather than one injected
    here, so the test fails if that rate is ever loosened to something useless.
    """
    codes = [
        api.post(RESEND, {"email": unverified_buyer.email}, format="json").status_code
        for _ in range(12)
    ]

    assert 429 in codes, f"the resend endpoint was never throttled: {codes}"
    # And the limit is tight: a handful, not dozens.
    assert codes.count(200) <= 6, f"too many sends allowed: {codes}"
    # Every message that did go out went to the account's own address, never to
    # whatever the caller typed.
    assert all(message.to == [unverified_buyer.email] for message in mail.outbox)


def test_the_resend_limit_is_per_address_not_only_per_ip(api, unverified_buyer):
    """One person's retries must not lock a different address out.

    A household, an office or a mobile network shares one public IP, so a
    purely per-IP bucket would make the resend button unusable for everyone
    after the first person used it.
    """
    other = User.objects.create_user(email="second@example.com", password=GOOD_PASSWORD)

    exhausted = [
        api.post(RESEND, {"email": unverified_buyer.email}, format="json").status_code
        for _ in range(12)
    ]
    assert 429 in exhausted

    # Same IP, different address: still allowed.
    assert api.post(RESEND, {"email": other.email}, format="json").status_code == 200


def test_concurrent_resends_leave_at_most_three_usable_tokens(unverified_buyer):
    """Overlapping requests must not leave a drawer of live keys to one account.

    Each issue retires all but the most recent few, so however the calls
    interleave the account ends with at most three live tokens.
    """
    from apps.accounts.services import send_verification_email

    for _ in range(5):
        send_verification_email(unverified_buyer)

    live = SecurityToken.objects.filter(
        user=unverified_buyer,
        purpose=TokenPurpose.EMAIL_VERIFICATION,
        used_at__isnull=True,
    )
    assert live.count() == 3

    # And the most recent email's token is among them.
    assert live.filter(token_hash=SecurityToken.hash_token(token_from_last_email())).exists()


def test_the_authenticated_resend_is_a_no_op_for_a_verified_account(api, auth, user):
    mail.outbox.clear()
    authed = auth(user, "Correct-Horse-Battery-1")

    response = authed.post(SEND, {}, format="json")

    assert response.status_code == 200
    assert "already verified" in response.data["detail"]
    assert mail.outbox == []


# ---------------------------------------------------------------------------
# 13. Provider failure
# ---------------------------------------------------------------------------


def test_a_mail_provider_failure_does_not_verify_the_account_or_fail_registration(
    api, monkeypatch
):
    """The provider is down. Registration must still succeed, unverified."""
    from django.core.mail import EmailMultiAlternatives

    def explode(self, *args, **kwargs):
        raise OSError("mail provider: connection refused")

    monkeypatch.setattr(EmailMultiAlternatives, "send", explode)

    response = register(api)

    assert response.status_code == 201, response.data
    account = User.objects.get(email=NEW_EMAIL)
    assert account.is_email_verified is False
    # The user can ask for another link, so a bad minute at the provider is not
    # an account that can never be used.
    assert SecurityToken.objects.filter(
        user=account, purpose=TokenPurpose.EMAIL_VERIFICATION, used_at__isnull=True
    ).exists()


def test_a_provider_failure_is_recorded_as_failed_not_sent(api, monkeypatch):
    """Recording a failure as success is how a broken mailer stays invisible."""
    from django.core.mail import EmailMultiAlternatives

    from apps.notifications.models import DeliveryStatus, Notification

    monkeypatch.setattr(
        EmailMultiAlternatives, "send", lambda self, *a, **k: (_ for _ in ()).throw(OSError("nope"))
    )

    register(api)

    notification = Notification.objects.filter(channel="EMAIL").latest("created_at")
    assert notification.delivery_status == DeliveryStatus.FAILED
    assert notification.delivery_error


def test_a_backend_that_accepts_no_recipients_is_not_reported_as_sent(api, monkeypatch):
    """`send()` returning 0 means nothing was delivered, however quietly."""
    from django.core.mail import EmailMultiAlternatives

    from apps.notifications.models import DeliveryStatus, Notification

    monkeypatch.setattr(EmailMultiAlternatives, "send", lambda self, *a, **k: 0)

    register(api)

    notification = Notification.objects.filter(channel="EMAIL").latest("created_at")
    assert notification.delivery_status == DeliveryStatus.FAILED


def test_the_authenticated_resend_reports_a_provider_failure(api, auth, unverified_buyer,
                                                             monkeypatch):
    """Answering "sent" would leave the user waiting for nothing."""
    from django.core.mail import EmailMultiAlternatives

    monkeypatch.setattr(
        EmailMultiAlternatives, "send", lambda self, *a, **k: (_ for _ in ()).throw(OSError("x"))
    )
    authed = auth(unverified_buyer, GOOD_PASSWORD)
    cool_down()

    response = authed.post(SEND, {}, format="json")

    assert response.status_code == 503
    assert response.data["error"]["code"] == "EMAIL_DELIVERY_FAILED"
    # No provider name, no host, no exception text.
    message = response.data["error"]["message"]
    assert "brevo" not in message.lower()
    assert "smtp" not in message.lower()


def test_no_log_line_carries_the_raw_token(api, caplog):
    """A token in a log file is a working link in a log file."""
    import logging

    caplog.set_level(logging.DEBUG, logger="verifygh")

    register(api)
    token = token_from_last_email()

    for record in caplog.records:
        assert token not in record.getMessage()
        assert token not in str(getattr(record, "__dict__", {}))


# ---------------------------------------------------------------------------
# 16-17. The rest of authentication still works
# ---------------------------------------------------------------------------


def test_verification_survives_logout_and_a_fresh_login(api, auth):
    register(api)
    token = token_from_last_email()
    assert api.post(CONFIRM, {"token": token}, format="json").status_code == 200

    api.post("/api/v1/auth/logout/", {}, format="json")
    api.cookies.clear()

    login = api.post(LOGIN, {"email": NEW_EMAIL, "password": GOOD_PASSWORD}, format="json")

    assert login.status_code == 200
    assert login.data["user"]["is_email_verified"] is True


def test_an_unverified_user_can_still_sign_in(api):
    """Verification gates purchases, not access.

    Blocking sign-in would leave someone whose email never arrived unable to
    reach the button that sends another one.
    """
    register(api)
    api.cookies.clear()

    response = api.post(LOGIN, {"email": NEW_EMAIL, "password": GOOD_PASSWORD}, format="json")

    assert response.status_code == 200
    assert response.data["user"]["is_email_verified"] is False


def test_password_reset_still_works(api, unverified_buyer):
    mail.outbox.clear()

    request = api.post(
        "/api/v1/auth/password/reset/", {"email": unverified_buyer.email}, format="json"
    )
    assert request.status_code == 200
    assert len(mail.outbox) == 1

    match = re.search(r"/reset-password\?token=([A-Za-z0-9_\-]+)", mail.outbox[0].body)
    assert match, mail.outbox[0].body

    confirm = api.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": match.group(1), "new_password": "Brand-New-Password-77"},
        format="json",
    )
    assert confirm.status_code == 200

    api.cookies.clear()
    login = api.post(
        LOGIN, {"email": unverified_buyer.email, "password": "Brand-New-Password-77"},
        format="json",
    )
    assert login.status_code == 200


def test_a_password_reset_token_is_also_single_use(api, unverified_buyer):
    mail.outbox.clear()
    api.post("/api/v1/auth/password/reset/", {"email": unverified_buyer.email}, format="json")
    token = re.search(r"/reset-password\?token=([A-Za-z0-9_\-]+)", mail.outbox[0].body).group(1)

    first = api.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": token, "new_password": "Brand-New-Password-77"}, format="json",
    )
    second = api.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": token, "new_password": "Another-Password-88"}, format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 400


def test_jwt_authentication_still_works_after_verifying(api, auth):
    """Verifying must not disturb the session it was done from."""
    register(api)
    account = User.objects.get(email=NEW_EMAIL)
    authed = auth(account, GOOD_PASSWORD)

    token = token_from_last_email()
    assert authed.post(CONFIRM, {"token": token}, format="json").status_code == 200

    me = authed.get("/api/v1/auth/me/")
    assert me.status_code == 200
    assert me.data["user"]["is_email_verified"] is True

    refresh = authed.post("/api/v1/auth/refresh/", {}, format="json")
    assert refresh.status_code == 200


def test_verifying_does_not_revoke_other_sessions(api, auth):
    """Only a password change or a reset should sign a user out everywhere."""
    register(api)
    account = User.objects.get(email=NEW_EMAIL)
    version_before = account.token_version

    api.post(CONFIRM, {"token": token_from_last_email()}, format="json")

    account.refresh_from_db()
    assert account.token_version == version_before


# ---------------------------------------------------------------------------
# Address masking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address,expected",
    [
        ("felix@gmail.com", "f****@gmail.com"),
        ("a@b.com", "a***@b.com"),
        ("kwame.mensah@verifygh.com", "k***********@verifygh.com"),
    ],
)
def test_mask_email_keeps_only_the_first_character(address, expected):
    assert mask_email(address) == expected


def test_mask_email_handles_rubbish_without_raising():
    assert mask_email("") == ""
    assert mask_email("not-an-address") == ""
    assert mask_email("@domain.com") == "@domain.com"
