"""A single error shape for the whole API.

Every non-2xx response the frontend can receive looks like:

    {"error": {"code": "INSUFFICIENT_FUNDS",
               "message": "Your balance is insufficient.",
               "details": {...},
               "request_id": "..."}}

Client code switches on `code`, never on the prose message.
"""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("verifygh.errors")


class APIError(Exception):
    """Base class for domain errors that map cleanly onto HTTP responses."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, details=None):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)


class ValidationFailed(APIError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"
    message = "Some of the information you entered is not valid."


class AuthenticationRequired(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTHENTICATION_REQUIRED"
    message = "Please sign in to continue."


class PermissionDeniedError(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action."


class NotFound(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "We could not find what you were looking for."


class Conflict(APIError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "That action conflicts with the current state."


class InsufficientFunds(APIError):
    status_code = status.HTTP_409_CONFLICT
    code = "INSUFFICIENT_FUNDS"
    message = "Your balance is insufficient."


class AccountSuspended(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "ACCOUNT_SUSPENDED"
    message = "This account is suspended. Please contact support."


class EmailNotVerified(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "EMAIL_NOT_VERIFIED"
    message = "Please verify your email address before making a purchase."


class TermsNotAccepted(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "TERMS_NOT_ACCEPTED"
    message = "You must accept the Terms and Acceptable Use Policy before purchasing."


class LimitExceeded(APIError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "LIMIT_EXCEEDED"
    message = "You have reached a usage limit. Please try again later."


class ServiceUnavailable(APIError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
    message = "This service is temporarily unavailable. Please try again shortly."


class ProviderError(APIError):
    """An upstream provider failed. Never leaks provider internals to the user."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "PROVIDER_ERROR"
    message = "We could not complete this with our provider. Please try again."


class InvalidStateTransition(Conflict):
    code = "INVALID_STATE_TRANSITION"
    message = "That action is not allowed for the current status."


def _envelope(code: str, message: str, details, request_id: str | None) -> dict:
    payload = {"code": code, "message": message}
    if details:
        payload["details"] = details
    if request_id:
        payload["request_id"] = request_id
    return {"error": payload}


def exception_handler(exc, context):
    """DRF exception handler producing the single error envelope above."""
    request = context.get("request")
    request_id = getattr(request, "request_id", None)

    if isinstance(exc, APIError):
        if exc.status_code >= 500:
            logger.exception("api_error", extra={"error_code": exc.code})
        return Response(
            _envelope(exc.code, exc.message, exc.details, request_id),
            status=exc.status_code,
        )

    if isinstance(exc, Http404):
        return Response(
            _envelope("NOT_FOUND", NotFound.message, None, request_id),
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, PermissionDenied):
        return Response(
            _envelope("PERMISSION_DENIED", PermissionDeniedError.message, None, request_id),
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            _envelope(
                "VALIDATION_ERROR",
                ValidationFailed.message,
                {"fields": getattr(exc, "message_dict", None) or exc.messages},
                request_id,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IntegrityError):
        # Usually a unique constraint doing its job (idempotency). Surface it as
        # a conflict rather than a 500 so clients can retry sensibly.
        logger.warning("integrity_error", exc_info=True)
        return Response(
            _envelope("CONFLICT", Conflict.message, None, request_id),
            status=status.HTTP_409_CONFLICT,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("unhandled_exception")
        return Response(
            _envelope("INTERNAL_ERROR", "Something went wrong on our side.", None, request_id),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    code = "ERROR"
    message = "The request could not be processed."
    details = None

    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
        code = getattr(detail["detail"], "code", "ERROR").upper()
    elif isinstance(detail, dict):
        code = "VALIDATION_ERROR"
        message = ValidationFailed.message
        details = {"fields": detail}
    elif isinstance(detail, list):
        code = "VALIDATION_ERROR"
        message = ValidationFailed.message
        details = {"errors": detail}

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "AUTHENTICATION_REQUIRED"
    elif response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        code = "RATE_LIMITED"
        message = "Too many requests. Please slow down and try again shortly."

    response.data = _envelope(code, message, details, request_id)
    return response
