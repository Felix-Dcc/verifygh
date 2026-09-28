"""Ghana Mobile Money across all three networks.

Written after a customer reported a Telecel deposit that never produced its
one-time code. What production actually showed:

    +233269...  network=AT   paystack=send_otp -> abandoned   otp_tries=0   (x3)

No Telecel payment existed at all. The number starts 026 - an AirtelTigo
prefix - and two things stood between its owner and the network they had
actually chosen:

  * the deposit form only offered a network selector when the prefix was
    unrecognised, so an 026 number was shown "Detected: AirtelTigo" with no
    way to say otherwise;
  * the backend, given a network that disagreed with the prefix, replaced it
    with the prefix anyway.

Ghana has had mobile number portability since 2011. A number keeps its prefix
when its owner moves network, so the prefix says who issued the number, not
where it lives now. The charge went to AirtelTigo Money, where this customer
has no wallet, and the code they were waiting for never came.

The provider codes themselves were correct throughout; these tests pin them
anyway, because a wrong one would fail in exactly the same silent way.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.conf import settings

from apps.accounts.constants import MomoNetwork
from apps.payments.base import ChargeStatus
from apps.payments.models import AWAITING_PAYMENT_STATUSES, Payment, PaymentStatus
from apps.payments.paystack import NETWORK_CODES, PaystackProvider
from apps.payments.serializers import DepositSerializer

pytestmark = pytest.mark.django_db

PASSWORD = "Correct-Horse-Battery-1"

#: Real Ghanaian prefixes, one per network.
NUMBERS = {
    MomoNetwork.MTN: "0241234567",
    MomoNetwork.TELECEL: "0201234567",
    MomoNetwork.AT: "0261234567",
}


# ---------------------------------------------------------------------------
# Provider codes - the values Paystack documents for Ghana
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "network,code",
    [(MomoNetwork.MTN, "mtn"), (MomoNetwork.AT, "atl"), (MomoNetwork.TELECEL, "vod")],
)
def test_each_network_maps_to_its_documented_paystack_code(network, code):
    assert NETWORK_CODES[network] == code


def test_every_supported_network_has_a_code():
    """A network offered in the form but missing here would fail at charge time."""
    assert set(NETWORK_CODES) == set(PaystackProvider.supported_networks)


def test_telecel_is_never_sent_under_its_marketing_name():
    """Paystack's code is `vod` - the network's old Vodafone identity."""
    assert "telecel" not in NETWORK_CODES.values()
    assert "airteltigo" not in NETWORK_CODES.values()


# ---------------------------------------------------------------------------
# The charge body, per network
# ---------------------------------------------------------------------------


class _Capture:
    def __init__(self, status="send_otp"):
        self.body = None
        self.status = status

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.body = kwargs.get("json")

        class R:
            status_code = 200
            content = b"x"

            def json(inner):
                return {"status": True, "data": {
                    "reference": self.body["reference"], "status": self.status,
                    "display_text": "Please enter the one-time password sent to your phone",
                }}

        return R()


@pytest.fixture
def paystack(settings):
    settings.PAYMENT_CREDENTIALS = {
        **settings.PAYMENT_CREDENTIALS,
        "paystack": {"secret_key": "sk_test_x", "base_url": "https://api.paystack.co"},
    }
    return PaystackProvider()


@pytest.mark.parametrize("network", list(NUMBERS))
def test_the_charge_carries_the_right_provider_code(paystack, network):
    capture = _Capture()
    paystack._session = capture

    paystack.initiate_charge(
        amount=Decimal("10.00"), currency="GHS", phone="+233241234567",
        network=network, reference="ref-x", email="a@b.com",
    )

    assert capture.body["mobile_money"]["provider"] == NETWORK_CODES[network]
    assert capture.body["currency"] == "GHS"
    assert capture.body["amount"] == 1000, "GHS 10.00 is 1000 pesewas"


@pytest.mark.parametrize("network", list(NUMBERS))
@pytest.mark.parametrize(
    "raw,expected",
    [("send_otp", ChargeStatus.OTP_REQUIRED),
     ("pay_offline", ChargeStatus.PHONE_AUTH_REQUIRED),
     ("pending", ChargeStatus.PENDING),
     ("success", ChargeStatus.SUCCESS),
     ("failed", ChargeStatus.FAILED)],
)
def test_every_network_honours_every_documented_state(paystack, network, raw, expected):
    """No network is assumed to follow another's flow."""
    paystack._session = _Capture(status=raw)

    charge = paystack.initiate_charge(
        amount=Decimal("10.00"), currency="GHS", phone="+233241234567",
        network=network, reference="ref-y", email="a@b.com",
    )

    assert charge.status is expected


# ---------------------------------------------------------------------------
# The root cause: whose network wins
# ---------------------------------------------------------------------------


def _validated(**body):
    body.setdefault("amount", "10.00")
    serializer = DepositSerializer(data=body)
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


def test_a_ported_number_keeps_the_network_its_owner_chose():
    """The regression test for the reported failure.

    An 026 number started on AirtelTigo. Its owner has moved it to Telecel and
    says so. The old code overrode them with the prefix, sent the charge to
    AirtelTigo Money, and the one-time code never arrived.
    """
    data = _validated(phone=NUMBERS[MomoNetwork.AT], network=MomoNetwork.TELECEL)

    assert data["network"] == MomoNetwork.TELECEL
    assert data["network_source"] == "customer"
    assert data["detected_network"] == MomoNetwork.AT


@pytest.mark.parametrize("network", list(NUMBERS))
def test_an_explicit_choice_is_honoured_for_every_prefix(network):
    """Porting works in every direction, not just away from AirtelTigo."""
    for chosen in NUMBERS:
        data = _validated(phone=NUMBERS[network], network=chosen)
        assert data["network"] == chosen


@pytest.mark.parametrize("network", list(NUMBERS))
def test_the_prefix_is_still_the_default_when_no_network_is_given(network):
    data = _validated(phone=NUMBERS[network])

    assert data["network"] == network
    assert data["network_source"] == "prefix"


def test_an_unrecognised_prefix_without_a_choice_asks_for_one():
    serializer = DepositSerializer(data={"amount": "10.00", "phone": "0301234567"})

    assert not serializer.is_valid()
    assert "network" in serializer.errors


@pytest.mark.parametrize("bad", ["telecel", "vodafone", "airteltigo", "vod", "atl", "mtn"])
def test_raw_or_marketing_network_names_are_refused(bad):
    """The browser picks a network from our list; it never sends a provider code
    straight through to Paystack."""
    serializer = DepositSerializer(
        data={"amount": "10.00", "phone": NUMBERS[MomoNetwork.MTN], "network": bad}
    )

    assert not serializer.is_valid()
    assert "network" in serializer.errors


@pytest.mark.parametrize(
    "raw,expected",
    [("0241234567", "+233241234567"),
     ("024 123 4567", "+233241234567"),
     ("+233241234567", "+233241234567"),
     ("233241234567", "+233241234567"),
     ("0201234567", "+233201234567"),
     ("0501234567", "+233501234567"),
     ("0261234567", "+233261234567"),
     ("0591234567", "+233591234567")],
)
def test_ghana_numbers_normalise_consistently(raw, expected):
    assert _validated(phone=raw, network=MomoNetwork.MTN)["phone"] == expected


# ---------------------------------------------------------------------------
# Evidence for the next report like this one
# ---------------------------------------------------------------------------


@pytest.fixture
def depositor(db):
    from apps.accounts.models import User

    account = User.objects.create_user(email="porter@example.com", password=PASSWORD,
                                       phone="+233261234567")
    account.is_email_verified = True
    account.accepted_terms_version = settings.VERIFYGH["CURRENT_TERMS_VERSION"]
    account.save(update_fields=["is_email_verified", "accepted_terms_version"])
    return account


def test_the_payment_records_both_the_choice_and_the_prefix(api, auth, depositor):
    """The old code overwrote the customer's choice and kept no trace of it, so
    a ported number that failed looked identical to a correct one."""
    response = auth(depositor, PASSWORD).post(
        "/api/v1/payments/deposit/",
        {"amount": "10.00", "phone": NUMBERS[MomoNetwork.AT], "network": "TELECEL"},
        format="json",
    )

    assert response.status_code == 201, response.data
    payment = Payment.objects.get(reference=response.data["reference"])
    assert payment.network == MomoNetwork.TELECEL
    assert payment.metadata["network_source"] == "customer"
    assert payment.metadata["prefix_network"] == MomoNetwork.AT


# ---------------------------------------------------------------------------
# The sweeps must see every unfinished state
# ---------------------------------------------------------------------------


def _stale(depositor, status, **extra):
    from datetime import timedelta

    from django.utils import timezone

    return Payment.objects.create(
        user=depositor, reference=f"VGH-PAY-{status[:8]}",
        provider="mock", provider_reference=f"VGH-PAY-{status[:8]}",
        amount=Decimal("10.00"), phone="+233261234567", network="AT", status=status,
        expires_at=timezone.now() - timedelta(minutes=1), **extra,
    )


def test_awaiting_statuses_cover_the_otp_and_handset_states():
    assert PaymentStatus.OTP_REQUIRED in AWAITING_PAYMENT_STATUSES
    assert PaymentStatus.PHONE_AUTH in AWAITING_PAYMENT_STATUSES


@pytest.mark.parametrize("status", [PaymentStatus.OTP_REQUIRED, PaymentStatus.PHONE_AUTH])
def test_the_expiry_sweep_settles_otp_and_handset_payments(depositor, status):
    """Found in production: four payments sat at OTP_REQUIRED and PHONE_AUTH
    while Paystack had long since marked them abandoned or failed.

    When those states were split out of PROCESSING, the sweep's filter was left
    at [PENDING, PROCESSING] and they became invisible to it.
    """
    from apps.payments.tasks import expire_stale_payments

    payment = _stale(depositor, status)

    expire_stale_payments()

    payment.refresh_from_db()
    assert payment.status not in AWAITING_PAYMENT_STATUSES, (
        f"a {status} payment past its expiry was left unsettled"
    )


@pytest.mark.parametrize("status", [PaymentStatus.OTP_REQUIRED, PaymentStatus.PHONE_AUTH])
def test_the_reconcile_sweep_asks_about_otp_and_handset_payments(depositor, status,
                                                                  monkeypatch):
    """The more serious half. This sweep recovers a deposit whose webhook was
    dropped - so leaving these states out of it meant a customer who approved
    late, and whose callback never arrived, would never have been credited."""
    from apps.payments import tasks

    seen = []
    monkeypatch.setattr(tasks, "reconcile_payment",
                        lambda payment: seen.append(payment.status) or payment)
    _stale(depositor, status)

    tasks.reconcile_recent_payments()

    assert status in seen, f"{status} payments were never reconciled"


def test_payments_stuck_awaiting_a_code_count_towards_the_pending_limit(depositor):
    """Otherwise a customer could stack up any number of them."""
    from apps.common.errors import LimitExceeded
    from apps.payments.services import _check_pending_deposits

    for i in range(3):
        Payment.objects.create(
            user=depositor, reference=f"VGH-PAY-STACK{i}", provider="mock",
            amount=Decimal("10.00"), phone="+233261234567", network="AT",
            status=PaymentStatus.OTP_REQUIRED,
        )

    with pytest.raises(LimitExceeded):
        _check_pending_deposits(depositor)


# ---------------------------------------------------------------------------
# The diagnostic view
# ---------------------------------------------------------------------------


@pytest.fixture
def diagnosed_payment(depositor):
    return Payment.objects.create(
        user=depositor, reference="VGH-PAY-DIAG0001", provider="paystack",
        provider_reference="VGH-PAY-DIAG0001", amount=Decimal("10.00"),
        phone="+233261234567", network="TELECEL", status=PaymentStatus.OTP_REQUIRED,
        instructions="Please enter the one-time password sent to your phone",
        metadata={"network_source": "customer", "prefix_network": "AT",
                  "provider_status_initial": "send_otp",
                  "provider_status_latest": "abandoned"},
    )


def test_staff_see_everything_needed_to_diagnose_a_failed_deposit(
    api, auth, admin_user, diagnosed_payment
):
    """Each of these fields answers one question from the Telecel report."""
    response = auth(admin_user, "Correct-Horse-Battery-3").get(
        f"/api/v1/admin/payments/{diagnosed_payment.reference}/"
    )

    assert response.status_code == 200, response.data
    data = response.data
    assert data["network"] == "TELECEL"               # what they chose
    assert data["prefix_network"] == "AT"             # what the number said
    assert data["network_source"] == "customer"       # whose call it was
    assert data["provider_status_initial"] == "send_otp"   # Paystack wanted a code
    assert data["provider_status_latest"] == "abandoned"   # and never got one
    assert data["otp_attempts"] == 0
    assert "one-time password" in data["instructions"]


def test_the_diagnostic_view_never_shows_the_full_number(api, auth, admin_user,
                                                          diagnosed_payment):
    response = auth(admin_user, "Correct-Horse-Battery-3").get(
        f"/api/v1/admin/payments/{diagnosed_payment.reference}/"
    )

    body = str(response.data)
    assert "261234567" not in body, "the full phone number reached a support screen"
    assert response.data["phone_suffix"] == "***4567"


def test_the_diagnostic_view_is_staff_only(api, auth, depositor, diagnosed_payment):
    response = auth(depositor, PASSWORD).get(
        f"/api/v1/admin/payments/{diagnosed_payment.reference}/"
    )

    assert response.status_code in (403, 404)


def test_the_initial_provider_status_is_recorded_at_charge_time(api, auth, depositor,
                                                               monkeypatch):
    """Otherwise the one detail that explains a stuck payment is lost.

    Driven through a provider that reports a raw status the way Paystack does;
    the mock adapter reports none, so it cannot exercise this.
    """
    from apps.payments import services as payment_services
    from apps.payments.base import ChargeDTO

    class PaystackLike:
        key = "paystack"
        supported_networks = ("MTN", "TELECEL", "AT")

        def initiate_charge(self, **kwargs):
            return ChargeDTO(
                provider_reference=kwargs["reference"], status=ChargeStatus.OTP_REQUIRED,
                instructions="Please enter the one-time password sent to your phone",
                raw={"status": "send_otp"},
            )

    monkeypatch.setattr(payment_services, "get_payment_provider",
                        lambda *a, **k: PaystackLike())

    response = auth(depositor, PASSWORD).post(
        "/api/v1/payments/deposit/",
        {"amount": "10.00", "phone": NUMBERS[MomoNetwork.AT], "network": "TELECEL"},
        format="json",
    )

    assert response.status_code == 201, response.data
    payment = Payment.objects.get(reference=response.data["reference"])
    assert payment.metadata["provider_status_initial"] == "send_otp"
    assert payment.metadata["provider_status_latest"] == "send_otp"
    assert payment.status == PaymentStatus.OTP_REQUIRED
    # Recording the diagnostic must not have clobbered what was already there.
    assert payment.metadata["network_source"] == "customer"
    assert payment.metadata["prefix_network"] == "AT"
