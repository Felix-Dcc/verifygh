"""Sign-up attribution: which campaign or site sent a new account."""

from __future__ import annotations

import pytest

from apps.accounts.attribution import clean_attribution
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"


@pytest.fixture(autouse=True)
def _run_commit_hooks(django_capture_on_commit_callbacks):
    # Registration queues its email on commit; run it so nothing is left pending.
    with django_capture_on_commit_callbacks(execute=True):
        yield


def register(api, **extra):
    return api.post(
        REGISTER,
        {
            "email": "ama@example.com",
            "password": "Correct-Horse-Battery-1",
            "accepted_terms": True,
            **extra,
        },
        format="json",
    )


def registered_metadata() -> dict:
    return AuditLog.objects.get(action="AUTH_REGISTER").metadata


def test_a_campaign_sign_up_is_recorded_on_the_audit_entry(api):
    response = register(api, attribution={
        "utm_source": "TikTok",
        "utm_medium": "paid_social",
        "utm_campaign": "oct-whatsapp-test",
        "utm_content": "Hook 3",
        "landing": "/",
        "referrer": "www.tiktok.com",
    })
    assert response.status_code == 201, response.content
    assert registered_metadata()["attribution"] == {
        "utm_source": "tiktok",
        "utm_medium": "paid_social",
        "utm_campaign": "oct-whatsapp-test",
        "utm_content": "hook_3",
        "landing": "/",
        "referrer": "www.tiktok.com",
    }


def test_a_sign_up_without_attribution_records_none(api):
    assert register(api).status_code == 201
    assert "attribution" not in registered_metadata()


@pytest.mark.parametrize("junk", ["tiktok", ["a", "b"], 42, None, {"utm_source": {"x": 1}}])
def test_junk_attribution_never_blocks_a_sign_up(api, junk):
    assert register(api, attribution=junk).status_code == 201
    assert "attribution" not in registered_metadata()


def test_values_are_cut_to_short_plain_tokens():
    cleaned = clean_attribution({
        "utm_source": "<script>alert(1)</script>",
        "landing": "/services?email=ama@example.com#top",
        "utm_campaign": "x" * 500,
        "unknown": "dropped",
    })
    assert cleaned == {
        "utm_source": "scriptalert1/script",
        "landing": "/services",
        "utm_campaign": "x" * 64,
    }
