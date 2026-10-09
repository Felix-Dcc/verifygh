"""Concurrency around the verification token.

"Single use" is easy to assert with two sequential requests and easy to get
wrong under simultaneous ones. The realistic trigger is not an attack: mail
clients and corporate link scanners prefetch links, so the scanner's GET and
the user's click can land on the same token milliseconds apart.

These run real threads on real connections. On PostgreSQL the conditional
`UPDATE ... WHERE used_at IS NULL` serialises them at row level; on SQLite the
BEGIN IMMEDIATE backend does. The assertions are on the invariant, so both are
proven.
"""

from __future__ import annotations

import threading

import pytest
from django.db import connections
from django.utils import timezone

from apps.accounts.models import SecurityToken, TokenPurpose, User
from apps.accounts.services import send_verification_email, verify_email
from apps.common.errors import ValidationFailed

pytestmark = pytest.mark.django_db(transaction=True)

PASSWORD = "Correct-Horse-Battery-1"


def run_concurrently(target, count: int) -> list:
    """Start `count` threads behind a barrier so they genuinely overlap."""
    results: list = [None] * count
    barrier = threading.Barrier(count)

    def _worker(index: int):
        try:
            barrier.wait(timeout=10)
            results[index] = ("ok", target(index))
        except Exception as exc:  # noqa: BLE001 - recorded, then asserted on
            results[index] = ("error", repr(exc))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


@pytest.fixture
def unverified(db):
    return User.objects.create_user(
        email="concurrent-verify@example.com", password=PASSWORD, full_name="Concurrent"
    )


def issue_token(user) -> str:
    """Issue a token directly, returning the raw value the email would carry."""
    _row, raw = SecurityToken.issue(
        user, TokenPurpose.EMAIL_VERIFICATION, 24, None
    )
    return raw


# ---------------------------------------------------------------------------
# One token, many simultaneous redemptions
# ---------------------------------------------------------------------------


def test_twenty_simultaneous_redemptions_consume_the_token_once(unverified):
    raw = issue_token(unverified)

    results = run_concurrently(lambda _index: verify_email(raw), 20)

    successes = [value for status, value in results if status == "ok"]
    failures = [value for status, value in results if status == "error"]

    assert len(successes) == 1, (
        f"the token was redeemed {len(successes)} times; single use is not holding"
    )
    assert len(failures) == 19
    # Every loser failed for the right reason, not on a database error that
    # happened to look like a refusal.
    assert all("INVALID_TOKEN" in failure or "ValidationFailed" in failure
               for failure in failures), failures

    unverified.refresh_from_db()
    assert unverified.is_email_verified is True

    # Exactly one row, consumed exactly once.
    tokens = SecurityToken.objects.filter(
        user=unverified, purpose=TokenPurpose.EMAIL_VERIFICATION
    )
    assert tokens.count() == 1
    assert tokens.first().used_at is not None


def test_the_account_is_verified_once_not_repeatedly(unverified):
    """`email_verified_at` must record the first verification, not the last."""
    raw = issue_token(unverified)

    run_concurrently(lambda _index: verify_email(raw), 10)

    unverified.refresh_from_db()
    first_timestamp = unverified.email_verified_at
    assert first_timestamp is not None

    # A replay afterwards changes nothing.
    with pytest.raises(ValidationFailed):
        verify_email(raw)
    unverified.refresh_from_db()
    assert unverified.email_verified_at == first_timestamp


# ---------------------------------------------------------------------------
# Many simultaneous resends
# ---------------------------------------------------------------------------


def test_simultaneous_resends_leave_no_more_than_three_live_tokens(unverified):
    """Overlapping resends must not leave a drawer of working links behind.

    Each issue retires all but the most recent few, so the invariant is "at
    most three live tokens" however the calls interleave.
    """
    run_concurrently(lambda _index: send_verification_email(unverified), 10)

    live = SecurityToken.objects.filter(
        user=unverified,
        purpose=TokenPurpose.EMAIL_VERIFICATION,
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    assert live.count() <= 3, (
        f"{live.count()} verification tokens are live at once; each resend must "
        "retire all but the most recent three"
    )


def test_a_resend_racing_a_redemption_never_verifies_twice(unverified):
    """The two operations that touch the token, at the same time.

    Whichever order they land in, the account ends up verified at most once and
    no unusable state is left behind.
    """
    raw = issue_token(unverified)

    def _worker(index: int):
        if index % 2 == 0:
            return verify_email(raw)
        return send_verification_email(unverified)

    results = run_concurrently(_worker, 10)

    verifications = [
        value for status, value in results
        if status == "ok" and isinstance(value, User)
    ]
    assert len(verifications) <= 1, "the token was redeemed more than once"

    unverified.refresh_from_db()
    # Nothing is half-done: either it verified, or it did not and a live token
    # still exists for the user to try again with.
    if not unverified.is_email_verified:
        assert SecurityToken.objects.filter(
            user=unverified,
            purpose=TokenPurpose.EMAIL_VERIFICATION,
            used_at__isnull=True,
        ).exists()


# ---------------------------------------------------------------------------
# One user's token is never another user's
# ---------------------------------------------------------------------------


def test_concurrent_verification_of_two_accounts_does_not_cross_over(unverified, db):
    """Two users verifying at once must each verify only themselves."""
    other = User.objects.create_user(email="second-concurrent@example.com", password=PASSWORD)

    first_token = issue_token(unverified)
    second_token = issue_token(other)

    def _worker(index: int):
        return verify_email(first_token if index % 2 == 0 else second_token)

    run_concurrently(_worker, 12)

    unverified.refresh_from_db()
    other.refresh_from_db()
    assert unverified.is_email_verified is True
    assert other.is_email_verified is True

    # Each account consumed its own token and only its own.
    for account in (unverified, other):
        rows = SecurityToken.objects.filter(
            user=account, purpose=TokenPurpose.EMAIL_VERIFICATION
        )
        assert rows.count() == 1
        assert rows.first().used_at is not None
