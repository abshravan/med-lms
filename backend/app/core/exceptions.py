"""Domain exceptions.

Services and repositories raise these. They carry a stable machine-readable
code and an HTTP status, and a single set of handlers (`middleware/error_handler`)
turns them into the standard response envelope. Routers therefore contain no
error-shaping logic at all.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable, machine-readable error codes.

    These are part of the API contract: clients branch on them. Reword the
    human-facing `message` freely, never these values.
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105 - an error code, not a credential
    TOKEN_INVALID = "TOKEN_INVALID"  # noqa: S105 - an error code, not a credential
    SESSION_REVOKED = "SESSION_REVOKED"
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    ACCOUNT_BANNED = "ACCOUNT_BANNED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base class for every expected failure in the application.

    Anything that is *not* an `AppError` reaching the handler layer is by
    definition a bug, and is reported as INTERNAL_ERROR without leaking detail.
    """

    status_code: int = 500
    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details
        self.headers = headers
        super().__init__(self.message)


# ── 400 / 422 ────────────────────────────────────────────────────────────────


class ValidationError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_ERROR
    message = "The submitted data is invalid."


# ── 401 ──────────────────────────────────────────────────────────────────────


class UnauthenticatedError(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHENTICATED
    message = "Authentication is required to access this resource."


class TokenExpiredError(UnauthenticatedError):
    code = ErrorCode.TOKEN_EXPIRED
    message = "Your access token has expired."


class TokenInvalidError(UnauthenticatedError):
    code = ErrorCode.TOKEN_INVALID
    message = "Your access token is invalid."


class SessionRevokedError(UnauthenticatedError):
    code = ErrorCode.SESSION_REVOKED
    message = "This session has been signed out. Please sign in again."


# ── 403 ──────────────────────────────────────────────────────────────────────


class ForbiddenError(AppError):
    status_code = 403
    code = ErrorCode.FORBIDDEN
    message = "You do not have permission to perform this action."


class EmailNotVerifiedError(AppError):
    status_code = 403
    code = ErrorCode.EMAIL_NOT_VERIFIED
    message = "Please verify your email address to continue."


class AccountBannedError(AppError):
    status_code = 403
    code = ErrorCode.ACCOUNT_BANNED
    message = "This account has been suspended."


# ── 404 / 409 / 429 ──────────────────────────────────────────────────────────


class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = ErrorCode.CONFLICT
    message = "The request conflicts with the current state of the resource."


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    message = "Too many requests. Please try again shortly."


# ── 5xx ──────────────────────────────────────────────────────────────────────


class UpstreamUnavailableError(AppError):
    status_code = 503
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    message = "A required upstream service is unavailable."


class InternalError(AppError):
    status_code = 500
    code = ErrorCode.INTERNAL_ERROR
    message = "An unexpected error occurred."
