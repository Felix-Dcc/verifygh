"""Restore the service logos lost with the Railway database (25 Nov 2026).

On 21 Oct 2026, 1,868 services were given the icon TextVerified shows for
them (a public PNG at textverified.com/ico/<id>/icon), each matched by name
and checked by eye, then uploaded through Admin > Catalog. The uploads lived
in the database; the mapping survived in that day's revert log and is kept in
apps/catalog/textverified_logos.json.

This command puts them back the way the admin upload does - validated, stored
in the database, served from /api/v1/service-logos/<slug>/, one audit record
each - and only where it cannot overwrite a decision:

* the service must still have the name it was matched under;
* it must have no logo, or a Brandfetch one (the owner preferred these icons);
  an uploaded or bundled logo is never replaced;
* each icon is fetched once, slowly, and must pass validate_logo.

    python manage.py restore_service_logos --admin owner@example.com --dry-run
    python manage.py restore_service_logos --admin owner@example.com
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

MAPPING = Path(__file__).resolve().parents[2] / "textverified_logos.json"
ICON_URL = "https://www.textverified.com/ico/{id}/icon"


class Command(BaseCommand):
    help = "Re-upload the TextVerified service icons matched on 21 Oct 2026."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True,
                            help="Email of the admin recorded as doing it.")
        parser.add_argument("--base-url", default="https://api.getverifygh.com",
                            help="Public API origin the logo URLs point at.")
        parser.add_argument("--dry-run", action="store_true", help="Report only; change nothing.")
        parser.add_argument("--pause", type=float, default=0.5, help="Seconds between downloads.")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many uploads.")

    def handle(self, *args, **options):
        from apps.accounts.constants import AdminPermission
        from apps.accounts.models import User
        from apps.adminapi.views import _invalidate_marketplace
        from apps.audit.services import record_admin_action
        from apps.catalog.brand_logos import is_brand_logo_url
        from apps.catalog.logos import validate_logo
        from apps.catalog.models import Service
        from apps.catalog.presentation import logo_key
        from apps.common.errors import ValidationFailed

        admin = User.objects.filter(email__iexact=options["admin"], is_active=True).first()
        if admin is None or not admin.has_admin_permission(AdminPermission.CATALOG_MANAGE):
            raise CommandError("--admin must be a staff account that manages the catalogue.")
        logos = json.loads(MAPPING.read_text(encoding="utf-8"))["logos"]
        base = options["base_url"].rstrip("/")
        session = requests.Session()
        session.headers["User-Agent"] = "VerifyGH logo restore"
        counts = {"restored": 0, "missing": 0, "renamed": 0, "has_logo": 0, "fetch_failed": 0,
                  "invalid": 0}

        for slug, (name, icon_id) in logos.items():
            if options["limit"] and counts["restored"] >= options["limit"]:
                break
            service = Service.objects.defer("logo_data").filter(slug=slug).first()
            if service is None:
                counts["missing"] += 1
                continue
            if logo_key(service.name) != logo_key(name):
                counts["renamed"] += 1
                continue
            if service.logo_content_type or (service.icon_url
                                             and not is_brand_logo_url(service.icon_url)):
                counts["has_logo"] += 1
                continue
            if options["dry_run"]:
                counts["restored"] += 1
                continue

            try:
                response = session.get(ICON_URL.format(id=icon_id), timeout=15)
                data = response.content if response.status_code == 200 else b""
            except requests.RequestException:
                data = b""
            time.sleep(options["pause"])
            if not data:
                counts["fetch_failed"] += 1
                self.stdout.write(f"FETCH_FAILED {slug}")
                continue
            try:
                content_type = validate_logo(data)
            except ValidationFailed:
                counts["invalid"] += 1
                self.stdout.write(f"INVALID {slug}")
                continue

            now = timezone.now()
            url = f"{base}/api/v1/service-logos/{slug}/?v={int(now.timestamp())}"
            with transaction.atomic():
                # Re-checked under the lock: nobody gave it a logo meanwhile.
                locked = Service.objects.select_for_update().defer("logo_data").get(pk=service.pk)
                if locked.logo_content_type or (locked.icon_url
                                                and not is_brand_logo_url(locked.icon_url)):
                    counts["has_logo"] += 1
                    continue
                Service.objects.filter(pk=service.pk).update(
                    logo_data=data, logo_content_type=content_type, logo_updated_at=now,
                    icon_url=url)
                record_admin_action(
                    admin=admin, action="SERVICE_LOGO_UPLOAD", target=service,
                    reason=(f"Restored TextVerified icon {icon_id} (matched 21 Oct 2026; "
                            "lost in the move to Render)"),
                    before={"icon_url": locked.icon_url},
                    after={"icon_url": url, "content_type": content_type})
            counts["restored"] += 1

        if not options["dry_run"]:
            _invalidate_marketplace()
        verb = "would restore" if options["dry_run"] else "restored"
        self.stdout.write(
            f"RESULT {verb}={counts['restored']} already_has_logo={counts['has_logo']} "
            f"renamed={counts['renamed']} not_in_catalogue={counts['missing']} "
            f"fetch_failed={counts['fetch_failed']} invalid={counts['invalid']}")
