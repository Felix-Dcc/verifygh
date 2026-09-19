"""Throttles.

DRF's scoped throttle only applies when a view sets `throttle_scope`; we want a
sane default on everything plus named, much tighter buckets on the endpoints
that matter (auth, deposits, order creation).
"""

from __future__ import annotations

import logging

from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger("verifygh.throttle")


class ResilientThrottleMixin:
    """Fail open, loudly, if the rate-limit cache is unreachable.

    Throttle state lives in Redis. Without this, a Redis blip turns every API
    request into a 500 - rate limiting becoming the outage. Failing open is
    acceptable because the controls that matter most do not depend on the
    cache: login has a database-backed account lockout, and money movement is
    protected by database constraints, not by throttles.
    """

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.error(
                "throttle_cache_unavailable",
                extra={"scope": getattr(self, "scope", "?")},
                exc_info=True,
            )
            return True


class ScopedBurstThrottle(ResilientThrottleMixin, SimpleRateThrottle):
    """Default throttle: per-user when authenticated, per-IP otherwise."""

    scope = "anon"

    def allow_request(self, request, view):
        # Pick the bucket before DRF reads self.rate.
        self.scope = "user" if (request.user and request.user.is_authenticated) else "anon"
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class NamedScopeThrottle(ResilientThrottleMixin, SimpleRateThrottle):
    """Base for named buckets. Subclasses set `scope`."""

    scope = "anon"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginThrottle(NamedScopeThrottle):
    scope = "login"

    def get_cache_key(self, request, view):
        # Throttle per-IP *and* per-submitted-identifier so one attacker cannot
        # spray many accounts from one IP, nor many IPs at one account.
        identifier = ""
        if isinstance(getattr(request, "data", None), dict):
            identifier = str(request.data.get("email", ""))[:128].lower()
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{self.get_ident(request)}:{identifier}",
        }


class LoginIPThrottle(NamedScopeThrottle):
    """Every sign-in attempt from one address, whatever email it names."""

    scope = "login_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class RegisterThrottle(NamedScopeThrottle):
    scope = "register"


class PasswordResetThrottle(NamedScopeThrottle):
    scope = "password_reset"


class EmailVerifyThrottle(NamedScopeThrottle):
    scope = "email_verify"


class DepositThrottle(NamedScopeThrottle):
    scope = "deposit"


class OrderCreateThrottle(NamedScopeThrottle):
    scope = "order_create"


class WebhookThrottle(NamedScopeThrottle):
    scope = "webhook"
