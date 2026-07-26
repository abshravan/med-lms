"""Auth routes.

Scope note: credential handling (sign-up, sign-in, verification, password reset)
lives in Better Auth on the Next.js origin under `/api/auth/*`. This router is
the *domain* side of authentication — identity as the API understands it. It does
not duplicate any Better Auth endpoint.

Handlers return domain models; `EnvelopedRoute` applies the response envelope.
See app/core/envelope.py for why this module avoids `from __future__ import
annotations`.
"""

from datetime import UTC, datetime

from fastapi import status

from app.core.dependencies import (
    AdminUserDep,
    AuthServiceDep,
    CurrentUserDep,
    RequestContextDep,
)
from app.core.envelope import create_router
from app.schemas.auth import (
    AuthDiagnostics,
    RevocationResult,
    UserProfileRead,
    UserProfileUpdate,
)
from app.schemas.common import SuccessResponse

router = create_router(prefix="/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=SuccessResponse[UserProfileRead],
    summary="Get the authenticated user's profile",
)
async def read_me(user: CurrentUserDep, service: AuthServiceDep) -> UserProfileRead:
    """Return the caller's profile.

    Available to unverified users on purpose: the client needs to know *who* it is
    talking to in order to render the "please verify your email" state at all.
    """
    return service.to_read_model(user)


@router.patch(
    "/me",
    response_model=SuccessResponse[UserProfileRead],
    summary="Update the authenticated user's profile",
)
async def update_me(
    payload: UserProfileUpdate,
    user: CurrentUserDep,
    service: AuthServiceDep,
    context: RequestContextDep,
) -> UserProfileRead:
    """Partially update the caller's own profile.

    The caller is always the subject — there is no `user_id` parameter, so this
    route cannot be pointed at somebody else's record.
    """
    return await service.update_profile(user, payload, context)


@router.post(
    "/sessions/revoke",
    response_model=SuccessResponse[RevocationResult],
    status_code=status.HTTP_200_OK,
    summary="Revoke the current session's access token",
)
async def revoke_current_session(
    user: CurrentUserDep,
    service: AuthServiceDep,
    context: RequestContextDep,
) -> RevocationResult:
    """Deny-list the caller's outstanding access token.

    The web client calls this *before* Better Auth's sign-out so that the
    already-issued JWT stops being accepted immediately, rather than remaining
    valid for the remainder of its 15-minute life.
    """
    ttl = await service.revoke_current_session(user, context)
    return RevocationResult(revoked=True, expires_in_seconds=ttl)


@router.get(
    "/session",
    response_model=SuccessResponse[AuthDiagnostics],
    summary="Inspect the current token (diagnostics)",
)
async def read_session(user: CurrentUserDep) -> AuthDiagnostics:
    """Return a non-sensitive view of the verified token.

    Exists so support can answer "what does the API think my session is?" without
    anyone pasting a token into a chat window.
    """
    expires_at = datetime.fromtimestamp(user.claims.expires_at, tz=UTC)
    remaining = int((expires_at - datetime.now(UTC)).total_seconds())
    return AuthDiagnostics(
        user_id=user.user_id,
        role=user.role.value,
        session_id=user.claims.session_id,
        email_verified=user.auth_user.email_verified,
        expires_at=expires_at,
        seconds_until_expiry=max(remaining, 0),
    )


@router.get(
    "/admin/ping",
    response_model=SuccessResponse[dict[str, str]],
    summary="Verify admin authorization",
)
async def admin_ping(user: AdminUserDep) -> dict[str, str]:
    """Confirm the caller holds the admin role.

    A deliberate, minimal admin-gated endpoint: it makes `require_role` testable
    end-to-end now, so the first real admin feature inherits a proven guard
    instead of being the thing that debugs it.
    """
    return {"role": user.role.value, "status": "authorized"}
