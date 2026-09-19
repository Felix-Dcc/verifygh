"""Permission classes.

Authorization is checked on *every* protected endpoint. User-facing viewsets
additionally filter their querysets by owner, so an object-level check can
never be the only thing standing between two users' data.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.accounts.constants import Role


class IsActiveUser(BasePermission):
    message = "This account is not active."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and not user.is_suspended)


class IsOwner(BasePermission):
    """Object belongs to the requesting user (checked via `user` or `wallet.user`)."""

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "user", None)
        if owner is None and hasattr(obj, "wallet"):
            owner = obj.wallet.user
        return owner is not None and owner == request.user


class HasRole(BasePermission):
    """Base for role gates. Subclasses set `allowed_roles`."""

    allowed_roles: tuple[str, ...] = ()
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active and not user.is_suspended):
            return False
        return user.role in self.allowed_roles


class IsSupport(HasRole):
    allowed_roles = (Role.SUPPORT, Role.ADMIN, Role.SUPER_ADMIN)


class IsAdmin(HasRole):
    allowed_roles = (Role.ADMIN, Role.SUPER_ADMIN)


class IsSuperAdmin(HasRole):
    allowed_roles = (Role.SUPER_ADMIN,)


class HasPermissionCode(BasePermission):
    """Fine-grained gate for sensitive admin operations.

    Views declare `required_permission = AdminPermission.WALLET_ADJUST` and the
    role matrix in apps/accounts/constants.py decides.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active and not user.is_suspended):
            return False
        required = getattr(view, "required_permission", None)
        if required is None:
            return True
        return user.has_admin_permission(required)
