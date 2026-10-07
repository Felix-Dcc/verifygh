"""Roles and the admin permission matrix.

Not every admin gets every power. Wallet adjustments, refunds and pricing
changes are the operations that can lose real money, so they sit behind
narrower roles and are always audited.
"""

from __future__ import annotations

from django.db import models


class Role(models.TextChoices):
    USER = "USER", "User"
    SUPPORT = "SUPPORT", "Support"
    ADMIN = "ADMIN", "Admin"
    SUPER_ADMIN = "SUPER_ADMIN", "Super admin"


class AdminPermission(models.TextChoices):
    USER_VIEW = "USER_VIEW", "View users"
    USER_SUSPEND = "USER_SUSPEND", "Suspend / unsuspend users"
    USER_ROLE_CHANGE = "USER_ROLE_CHANGE", "Change user roles"
    WALLET_VIEW = "WALLET_VIEW", "View wallets and ledgers"
    WALLET_ADJUST = "WALLET_ADJUST", "Adjust wallet balances"
    ORDER_VIEW = "ORDER_VIEW", "View orders"
    ORDER_CANCEL = "ORDER_CANCEL", "Cancel orders"
    ORDER_REFUND = "ORDER_REFUND", "Issue refunds"
    PAYMENT_VIEW = "PAYMENT_VIEW", "View payments"
    CATALOG_MANAGE = "CATALOG_MANAGE", "Enable/disable services and countries"
    PRICING_VIEW = "PRICING_VIEW", "See provider costs, FX, markup and margins"
    PRICING_MANAGE = "PRICING_MANAGE", "Change pricing: FX, markup, overrides, publishing"
    PRICING_LOSS_OVERRIDE = "PRICING_LOSS_OVERRIDE", "Approve a price below provider cost"
    PROVIDER_MANAGE = "PROVIDER_MANAGE", "Configure providers"
    AUDIT_VIEW = "AUDIT_VIEW", "View the audit log"
    REFERRAL_VIEW = "REFERRAL_VIEW", "View referrals and referral analytics"
    REFERRAL_MANAGE = "REFERRAL_MANAGE", "Approve, reject and flag referrals"
    METRICS_VIEW = "METRICS_VIEW", "View dashboards and metrics"
    ISSUE_MANAGE = "ISSUE_MANAGE", "Review, reject and resolve number-issue reports"
    USER_EMAIL_CHANGE = "USER_EMAIL_CHANGE", "Correct a user's unverified email address"
    MAINTENANCE_MANAGE = "MAINTENANCE_MANAGE", "Pause and reopen the site"


_SUPPORT = {
    AdminPermission.USER_VIEW,
    AdminPermission.WALLET_VIEW,
    AdminPermission.ORDER_VIEW,
    AdminPermission.PAYMENT_VIEW,
    AdminPermission.METRICS_VIEW,
    AdminPermission.REFERRAL_VIEW,
}

_ADMIN = _SUPPORT | {
    AdminPermission.USER_SUSPEND,
    # Only ever an unverified address, and audited; still an account change,
    # so not support.
    AdminPermission.USER_EMAIL_CHANGE,
    AdminPermission.ORDER_CANCEL,
    AdminPermission.ORDER_REFUND,
    AdminPermission.CATALOG_MANAGE,
    AdminPermission.AUDIT_VIEW,
    # Approving a held referral issues promotional credit, so it stays with
    # admins. Reversing one needs WALLET_ADJUST, which is super-admin only.
    AdminPermission.REFERRAL_MANAGE,
    # Moving a report along without money. Refunds and replacements still
    # need ORDER_REFUND.
    AdminPermission.ISSUE_MANAGE,
    # Admins can see what things cost and earn; changing prices stays with
    # super admins, who act as finance.
    AdminPermission.PRICING_VIEW,
    # Pausing the site in an emergency: stops new orders and top-ups, never
    # money already moving.
    AdminPermission.MAINTENANCE_MANAGE,
}

_SUPER_ADMIN = _ADMIN | {
    AdminPermission.USER_ROLE_CHANGE,
    AdminPermission.WALLET_ADJUST,
    AdminPermission.PRICING_MANAGE,
    AdminPermission.PRICING_LOSS_OVERRIDE,
    AdminPermission.PROVIDER_MANAGE,
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.USER: set(),
    Role.SUPPORT: {str(p) for p in _SUPPORT},
    Role.ADMIN: {str(p) for p in _ADMIN},
    Role.SUPER_ADMIN: {str(p) for p in _SUPER_ADMIN},
}

STAFF_ROLES = (Role.SUPPORT, Role.ADMIN, Role.SUPER_ADMIN)


class MomoNetwork(models.TextChoices):
    """The three MoMo networks that matter in Ghana today."""

    MTN = "MTN", "MTN Mobile Money"
    TELECEL = "TELECEL", "Telecel Cash"
    AT = "AT", "AT Money"


# Ghanaian mobile prefixes, used to infer the network from a phone number so the
# user does not have to pick one. Source: NCA number allocations.
NETWORK_PREFIXES: dict[str, tuple[str, ...]] = {
    MomoNetwork.MTN: ("024", "025", "053", "054", "055", "059"),
    MomoNetwork.TELECEL: ("020", "050"),
    MomoNetwork.AT: ("026", "027", "056", "057"),
}
