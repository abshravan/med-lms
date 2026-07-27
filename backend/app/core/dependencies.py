"""FastAPI dependencies: the authentication and authorization chain.

The chain is deliberately granular so each route declares exactly the guarantee
it needs, and nothing more:

    get_db_session          → a unit of work
    get_auth_service        → wired service
    get_token_claims        → signature / issuer / audience / expiry verified
    get_current_user        → + not revoked, exists, not banned, profile hydrated
    get_verified_user       → + email verified
    require_role(...)       → + role authorised (re-checked against the database)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.exceptions import ForbiddenError, SessionRevokedError, UnauthenticatedError
from app.core.redis import is_revoked
from app.core.security import TokenClaims, verify_access_token
from app.middleware.request_context import get_request_id
from app.models.profile import UserRole
from app.repositories.course_repository import CourseRepository
from app.repositories.media_repository import MediaRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthenticatedUser, AuthService, RequestContext
from app.services.course_service import CourseService
from app.services.media_service import MediaService
from app.services.storage import StorageProvider, get_storage_provider

# auto_error=False so a missing header raises our own enveloped 401 rather than
# FastAPI's bare `{"detail": ...}`, which would break the response contract.
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BetterAuthAccessToken")

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_request_context(request: Request) -> RequestContext:
    """Extract audit metadata from the request."""
    return RequestContext(
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=get_request_id() or None,
    )


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


def get_user_repository(session: SessionDep) -> UserRepository:
    """Provide a request-scoped user repository."""
    return UserRepository(session)


def get_auth_service(
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> AuthService:
    """Provide a request-scoped auth service."""
    return AuthService(repository)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_course_repository(session: SessionDep) -> CourseRepository:
    """Provide a request-scoped course repository."""
    return CourseRepository(session)


def get_course_service(
    repository: Annotated[CourseRepository, Depends(get_course_repository)],
) -> CourseService:
    """Provide a request-scoped course service."""
    return CourseService(repository)


CourseServiceDep = Annotated[CourseService, Depends(get_course_service)]


def get_media_repository(session: SessionDep) -> MediaRepository:
    """Provide a request-scoped media repository."""
    return MediaRepository(session)


def get_storage() -> StorageProvider:
    """Provide the configured storage backend.

    A dependency rather than a direct import so tests can override the backend
    per-request without touching the process-wide factory.
    """
    return get_storage_provider()


def get_media_service(
    repository: Annotated[MediaRepository, Depends(get_media_repository)],
    storage: Annotated[StorageProvider, Depends(get_storage)],
) -> MediaService:
    """Provide a request-scoped media service."""
    settings: Settings = get_settings()
    return MediaService(repository, storage, settings)


MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]


async def get_token_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TokenClaims:
    """Verify the bearer token and return its claims.

    Cryptographic checks only — no database access. Cheap enough to sit in front
    of everything.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthenticatedError("An access token is required.")
    return await verify_access_token(credentials.credentials)


TokenClaimsDep = Annotated[TokenClaims, Depends(get_token_claims)]


async def get_current_user(
    claims: TokenClaimsDep,
    service: AuthServiceDep,
    context: RequestContextDep,
) -> AuthenticatedUser:
    """Resolve the fully authenticated caller.

    Adds to `get_token_claims`: revocation check, existence, ban status, and
    profile hydration.
    """
    if await is_revoked(session_id=claims.session_id, user_id=claims.user_id):
        raise SessionRevokedError()
    return await service.resolve_authenticated_user(claims, context)


CurrentUserDep = Annotated[AuthenticatedUser, Depends(get_current_user)]


async def get_verified_user(
    user: CurrentUserDep,
    service: AuthServiceDep,
) -> AuthenticatedUser:
    """Require a verified email address.

    This is the guard content routes will use once there is content to serve.
    """
    service.require_verified_email(user)
    return user


VerifiedUserDep = Annotated[AuthenticatedUser, Depends(get_verified_user)]


def require_role(
    *allowed: UserRole,
) -> Callable[[AuthenticatedUser, AuthService, RequestContext], Awaitable[AuthenticatedUser]]:
    """Build a dependency that authorises the caller against a set of roles.

    The role is taken from `AuthenticatedUser.role`, which reads the database
    rather than the token claim. That closes the window where a token minted
    before a demotion still asserts the old role — see docs/architecture.md §3.4.

    Usage:
        @router.get("/admin/thing", dependencies=[Depends(require_role(UserRole.ADMIN))])
    """
    allowed_roles = frozenset(allowed)

    async def dependency(
        user: CurrentUserDep,
        service: AuthServiceDep,
        context: RequestContextDep,
    ) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            await service.record_access_denied(
                user,
                context,
                required_role="|".join(sorted(role.value for role in allowed_roles)),
            )
            raise ForbiddenError()
        return user

    return dependency


AdminUserDep = Annotated[AuthenticatedUser, Depends(require_role(UserRole.ADMIN))]


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP.

    `X-Forwarded-For` is only consulted because this API always runs behind a
    trusted proxy that overwrites it. If it were ever exposed directly, this value
    would be attacker-controlled — it is used for audit context only, never for
    an authorization decision.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None
