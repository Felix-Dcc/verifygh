"""restore_service_logos: puts back the TextVerified icons matched on 21 Oct 2026."""

from __future__ import annotations

import json
import struct
import zlib

import pytest
from django.core.management import CommandError, call_command

from apps.audit.models import AdminAction
from apps.catalog.management.commands import restore_service_logos as cmd
from apps.catalog.models import Service

pytestmark = pytest.mark.django_db


def _png(side=128) -> bytes:
    def chunk(kind, data):
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * side for _ in range(side))
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
    return (b"\x89PNG\r\n\x1a\n" + header
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class _Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code = content, status


@pytest.fixture
def mapping(tmp_path, monkeypatch):
    path = tmp_path / "logos.json"
    path.write_text(json.dumps({"logos": {
        "lemon8": ["Lemon8", "trgt_LEMON"],
        "bumble": ["Bumble", "trgt_BUMBLE"],
        "renamed": ["Old Name", "trgt_RENAMED"],
        "uploaded": ["Uploaded", "trgt_UP"],
        "bundled": ["Bundled", "trgt_BUN"],
        "tiny": ["Tiny", "trgt_TINY"],
        "gone": ["Gone", "trgt_GONE"],
    }}), encoding="utf-8")
    monkeypatch.setattr(cmd, "MAPPING", path)
    monkeypatch.setattr(cmd.time, "sleep", lambda s: None)
    fetched = []

    def get(self, url, timeout=None):
        fetched.append(url)
        return _Resp(_png(32) if "TINY" in url else _png())
    monkeypatch.setattr(cmd.requests.Session, "get", get)
    return fetched


@pytest.fixture
def services(db):
    Service.objects.create(slug="lemon8", name="Lemon8")
    Service.objects.create(slug="bumble", name="Bumble",
                           icon_url="https://cdn.brandfetch.io/domain/bumble.com/w/128/h/128/type/icon/fallback/404?c=abcdef123")
    Service.objects.create(slug="renamed", name="Something Else")
    Service.objects.create(slug="uploaded", name="Uploaded", logo_content_type="image/png",
                           icon_url="https://api.getverifygh.com/api/v1/service-logos/uploaded/?v=1")
    Service.objects.create(slug="bundled", name="Bundled", icon_url="/service-icons/bundled.svg")
    Service.objects.create(slug="tiny", name="Tiny")


def test_restores_only_where_it_cannot_overwrite_a_decision(mapping, services, admin_user):
    call_command("restore_service_logos", admin=admin_user.email)

    lemon, bumble = Service.objects.get(slug="lemon8"), Service.objects.get(slug="bumble")
    assert lemon.logo_content_type == "image/png"
    assert bytes(lemon.uploaded_logo.data).startswith(b"\x89PNG")
    assert lemon.icon_url.startswith("https://api.getverifygh.com/api/v1/service-logos/lemon8/?v=")
    assert bumble.logo_content_type == "image/png"            # Brandfetch replaced
    assert Service.objects.get(slug="renamed").icon_url == ""  # name changed: left alone
    assert Service.objects.get(slug="uploaded").icon_url.endswith("?v=1")
    assert Service.objects.get(slug="bundled").icon_url == "/service-icons/bundled.svg"
    assert Service.objects.get(slug="tiny").logo_content_type == ""  # too small: refused
    assert not any("RENAMED" in u or "UP" in u.split("/")[-2] or "BUN" in u for u in mapping)
    assert AdminAction.objects.filter(action="SERVICE_LOGO_UPLOAD").count() == 2


def test_dry_run_changes_nothing(mapping, services, admin_user):
    call_command("restore_service_logos", admin=admin_user.email, dry_run=True)
    assert mapping == []
    assert Service.objects.get(slug="lemon8").icon_url == ""
    assert not AdminAction.objects.exists()


def test_a_customer_account_cannot_run_it(mapping, services, user):
    with pytest.raises(CommandError):
        call_command("restore_service_logos", admin=user.email)


def test_the_shipped_mapping_is_well_formed():
    logos = json.loads(cmd.MAPPING.read_text(encoding="utf-8"))["logos"]
    assert len(logos) == 2058
    assert all(name and icon.startswith("trgt") for name, icon in logos.values())
