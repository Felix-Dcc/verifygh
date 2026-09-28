"""Report accounts whose authentication state could stop their owner signing in.

    python manage.py audit_authentication

Read-only. It never modifies an account, never prints a password hash, a token
or a full email address - accounts are identified by id and a masked address.

Written while chasing "I can register but not sign in, and resetting my
password doesn't help". Each category below is a way that report can happen
that is invisible from the login screen, where every one of them looks like a
wrong password.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.accounts.models import LoginAttempt, User


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"


class Command(BaseCommand):
    help = "Report accounts in an authentication state that could block sign-in (read-only)."

    def handle(self, *args, **options):
        findings = 0

        def section(title: str, rows: list[str], why: str) -> None:
            nonlocal findings
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{title}  ({len(rows)})"))
            self.stdout.write(f"  {why}")
            for row in rows:
                self.stdout.write(f"  - {row}")
            findings += len(rows)

        # 1. Two accounts that differ only by case. Login lowercases and uses
        #    iexact, so it would pick one of them arbitrarily.
        dupes = (
            User.objects.annotate(canonical=Lower("email"))
            .values("canonical")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        section(
            "Duplicate emails ignoring case",
            [f"{_mask(d['canonical'])} x{d['n']}" for d in dupes],
            "Sign-in would resolve to whichever row the database returns first.",
        )

        # 2. Stored with capitals. Harmless today - login lowercases - but every
        #    creation path lowercases, so a row like this was made some other way.
        section(
            "Emails not stored in lowercase",
            [f"#{u.pk} {_mask(u.email)}"
             for u in User.objects.exclude(email=Lower("email")).only("pk", "email")],
            "Every normal creation path lowercases; these came from somewhere else.",
        )

        # 3. No usable password at all. check_password always fails.
        section(
            "Unusable or empty password",
            [f"#{u.pk} {_mask(u.email)}"
             for u in User.objects.filter(Q(password="") | Q(password__startswith="!"))
             .only("pk", "email")],
            "No password can ever match. The owner must reset it.",
        )

        # 4. Deactivated. Django's backend refuses these with the correct password,
        #    and the login screen reports it as a wrong password.
        section(
            "Inactive accounts",
            [f"#{u.pk} {_mask(u.email)}"
             for u in User.objects.filter(is_active=False).only("pk", "email")],
            "Rejected even with the right password, and shown as 'incorrect'.",
        )

        # 5. Locked right now.
        now = timezone.now()
        section(
            "Currently locked out",
            [f"#{u.pk} {_mask(u.email)} until {u.locked_until:%H:%M}"
             for u in User.objects.filter(locked_until__gt=now).only("pk", "email",
                                                                    "locked_until")],
            "Clears on its own at the time shown, or on a password reset.",
        )

        # 6. Suspended.
        section(
            "Suspended",
            [f"#{u.pk} {_mask(u.email)}"
             for u in User.objects.filter(is_suspended=True).only("pk", "email")],
            "Deliberate. Listed so it is not mistaken for a fault.",
        )

        # 7. The pattern behind the original report: failures and never a success.
        failed = defaultdict(int)
        succeeded = set()
        for user_id, ok in LoginAttempt.objects.filter(user__isnull=False).values_list(
            "user_id", "successful"
        ):
            if ok:
                succeeded.add(user_id)
            else:
                failed[user_id] += 1
        never = [uid for uid, n in failed.items() if uid not in succeeded and n >= 2]
        users = {u.pk: u for u in User.objects.filter(pk__in=never).only("pk", "email")}
        section(
            "Repeated failures and never a successful sign-in",
            [f"#{uid} {_mask(users[uid].email)}  {failed[uid]} failures"
             for uid in never if uid in users],
            "Worth contacting. Includes anyone hit by the password whitespace "
            "mismatch fixed on 2026-09-28.",
        )

        self.stdout.write("")
        if findings:
            self.stdout.write(self.style.WARNING(f"{findings} finding(s). Nothing was changed."))
        else:
            self.stdout.write(self.style.SUCCESS("No findings. Nothing was changed."))
