"""Service logos: the bundled set, uploads, and what an upload may contain."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.audit.models import AdminAction
from apps.catalog.models import Service
from apps.catalog.presentation import bundled_icon_url
from apps.orders.models import Order
from apps.verification import mock as verification_mock

pytestmark = pytest.mark.django_db

REPO = Path(__file__).resolve().parents[2]
ICON_DIR = REPO / "frontend" / "public" / "service-icons"
MAPPING = json.loads(
    (REPO / "backend" / "apps" / "catalog" / "service_icons.json").read_text(encoding="utf-8")
)["icons"]

GOOD_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            b'<defs><linearGradient id="g"><stop offset="0" stop-color="#000"/></linearGradient></defs>'
            b'<path fill="url(#g)" d="M0 0h24v24H0z"/></svg>')


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


def sign_in(account, password) -> APIClient:
    client = APIClient()
    response = client.post("/api/v1/auth/login/", {"email": account.email, "password": password},
                           format="json")
    assert response.status_code == 200, response.data
    client.credentials(HTTP_X_CSRF_TOKEN=response.data["csrf_token"])
    return client


@pytest.fixture
def staff(admin_user):
    return sign_in(admin_user, "Correct-Horse-Battery-3")


def upload(client, slug, data, name="logo.svg"):
    return client.post(f"/api/v1/admin/services/{slug}/logo/",
                       {"file": SimpleUploadedFile(name, data), "reason": "Brand refresh"},
                       format="multipart")


# ---------------------------------------------------------------------------
# The bundled set
# ---------------------------------------------------------------------------


def test_every_mapped_service_has_a_generated_logo_and_a_recorded_source():
    sources = json.loads((ICON_DIR / "SOURCES.json").read_text(encoding="utf-8"))["icons"]

    for slug in MAPPING:
        svg = (ICON_DIR / f"{slug}.svg").read_text(encoding="utf-8")
        assert svg.startswith("<svg") and "<script" not in svg, slug
        assert f"{sources[slug]['title']}" in svg
        assert sources[slug]["source"].startswith("http"), slug


def test_no_generated_file_is_left_without_a_mapping():
    generated = {path.stem for path in ICON_DIR.glob("*.svg")}
    assert generated == set(MAPPING)


def test_sync_gives_known_services_their_logo(catalog):
    assert Service.objects.get(slug="tiktok").icon_url == "/service-icons/tiktok.svg"
    assert Service.objects.get(slug="x").icon_url == "/service-icons/x.svg"
    # Not bundled (the brand withdrew its mark from Simple Icons): no logo, so
    # the frontend's fallback shows - never a guessed image.
    assert Service.objects.get(slug="paypal").icon_url == ""
    assert bundled_icon_url("linkedin") == ""


def test_the_marketplace_and_orders_carry_the_logo(api, catalog, user, funded_wallet,
                                                  django_capture_on_commit_callbacks):
    rows = api.get("/api/v1/marketplace/").data["results"]
    assert next(r for r in rows if r["slug"] == "tiktok")["icon_url"] == "/service-icons/tiktok.svg"

    funded_wallet(user, "100.00")
    client = sign_in(user, "Correct-Horse-Battery-1")
    verification_mock.force_scenario("HAPPY")
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/api/v1/orders/", {"service": "tiktok", "country": "US"}, format="json")

    listed = client.get("/api/v1/orders/").data["results"][0]
    assert listed["service_icon"] == "/service-icons/tiktok.svg"
    assert Order.objects.count() == 1


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


def test_an_uploaded_svg_replaces_the_logo_and_is_served_inert(staff, catalog):
    response = upload(staff, "tiktok", GOOD_SVG)

    assert response.status_code == 200, response.data
    url = response.data["icon_url"]
    assert "/api/v1/service-logos/tiktok/?v=" in url
    assert response.data["has_uploaded_logo"] is True
    assert AdminAction.objects.filter(action="SERVICE_LOGO_UPLOAD").exists()

    served = APIClient().get("/api/v1/service-logos/tiktok/")
    assert served.status_code == 200
    assert served["Content-Type"] == "image/svg+xml"
    assert served.content == GOOD_SVG
    assert "sandbox" in served["Content-Security-Policy"]
    assert "immutable" in served["Cache-Control"]


def test_a_large_enough_png_is_accepted(staff, catalog):
    response = upload(staff, "tiktok", png(256, 256), name="logo.png")

    assert response.status_code == 200, response.data
    assert APIClient().get("/api/v1/service-logos/tiktok/")["Content-Type"] == "image/png"


@pytest.mark.parametrize("data", [
    pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', id="script"),
    pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', id="handler"),
    pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink">'
     b'<image x:href="https://evil.example/x.png"/></svg>', id="external href"),
    pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><path/></a></svg>', id="javascript link"),
    pytest.param(b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg"/>', id="entities"),
    pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>', id="foreignObject"),
    pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg"><path style="fill:url(https://evil.example/a)"/></svg>', id="external url()"),
    pytest.param(b"<html><body>hi</body></html>", id="not an image"),
    pytest.param(b"GIF89a....", id="wrong format"),
    pytest.param(b"<svg" + b" " * (200 * 1024) + b"/>", id="too large"),
])
def test_unsafe_or_unsuitable_uploads_are_refused(staff, catalog, data):
    response = upload(staff, "tiktok", data)

    assert response.status_code == 400
    assert Service.objects.get(slug="tiktok").icon_url == "/service-icons/tiktok.svg"


def test_a_small_png_is_refused_as_blurry(staff, catalog):
    assert upload(staff, "tiktok", png(32, 32), name="x.png").status_code == 400


def test_removing_an_upload_returns_to_the_bundled_logo(staff, catalog):
    upload(staff, "tiktok", GOOD_SVG)

    response = staff.delete("/api/v1/admin/services/tiktok/logo/")

    assert response.data["icon_url"] == "/service-icons/tiktok.svg"
    assert response.data["has_uploaded_logo"] is False
    assert APIClient().get("/api/v1/service-logos/tiktok/").status_code == 404


def test_only_bundled_or_uploaded_logos_can_be_set(staff, catalog):
    external = staff.patch("/api/v1/admin/services/tiktok/",
                           {"icon_url": "https://example.com/tiktok.png", "reason": "try"},
                           format="json")
    assert external.status_code == 400

    bundled = staff.patch("/api/v1/admin/services/paypal/",
                          {"icon_url": "/service-icons/paypal.svg", "reason": "set"},
                          format="json")
    assert bundled.status_code == 200
    cleared = staff.patch("/api/v1/admin/services/tiktok/", {"icon_url": "", "reason": "hide"},
                          format="json")
    assert cleared.status_code == 200 and cleared.data["icon_url"] == ""


def test_branding_is_staff_only(api, catalog, support_user, user):
    support = sign_in(support_user, "Correct-Horse-Battery-4")
    customer = sign_in(user, "Correct-Horse-Battery-1")

    assert upload(support, "tiktok", GOOD_SVG).status_code == 403
    assert upload(customer, "tiktok", GOOD_SVG).status_code == 403
    assert upload(api, "tiktok", GOOD_SVG).status_code in (401, 403)
    assert not Service.objects.get(slug="tiktok").logo_content_type
