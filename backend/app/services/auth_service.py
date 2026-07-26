"""Authentication and profile business logic.

This service owns the transaction boundary for auth operations and is the only
place that decides *policy* — who may act, what counts as verified, when a
profile is created. Routers translate HTTP to calls here; repositories translate
calls here to SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.exceptions import (
    AccountBannedError,
    EmailNotVerifiedError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.core.redis import revoke_session, revoke_user
from app.core.security import TokenClaims
from app.models.auth import AuthUser
from app.models.profile import AuthEvent, AuthOutcome, UserProfile, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.auth import UserProfileRead, UserProfileUpdate

logger = get_logger(__name__)

# Must match the `expirationTime` configured on the Better Auth jwt plugin.
# A deny-list entry only needs to outlive the tokens it is suppressing.
ACCESS_TOKEN_TTL_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Non-authenticating request metadata, used for the audit trail."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """A verified caller: token claims plus persisted identity and profile."""

    claims: TokenClaims
    profile: UserProfile
    auth_user: AuthUser

    @property
    def user_id(self) -> str:
        return self.claims.user_id

    @property
    def role(self) -> UserRole:
        """The authoritative role, read from the database rather than the token."""
        return self.profile.role

    @property
    def is_admin(self) -> bool:
        return self.profile.role is UserRole.ADMIN


class AuthService:
    """Auth use cases. One instance per request."""

    def __init__(self, repository: UserRepository) -> None:
        self._repo = repository

    # ── Resolution ───────────────────────────────────────────────────────────

    async def resolve_authenticated_user(
        self, claims: TokenClaims, context: RequestContext
    ) -> AuthenticatedUser:
        """Turn verified claims into a fully hydrated caller.

        Also the lazy profile-creation point: a user who registered while this API
        was unavailable gets their profile on first authenticated request instead
        of being permanently broken.

        Raises:
            NotFoundError: The token is validly signed but names a user that no
                longer exists — e.g. a deleted account whose token has not yet
                expired.
            AccountBannedError: The account is suspended.
        """
        auth_user = await self._repo.get_auth_user(claims.user_id)
        if auth_user is None:
            await self._repo.record_audit_event(
                event=AuthEvent.TOKEN_REJECTED,
                outcome=AuthOutcome.FAILURE,
                user_id=claims.user_id,
                ip_address=context.ip_address,
                user_agent=context.user_agent,
                request_id=context.request_id,
                metadata={"reason": "user_not_found"},
            )
            await self._repo.session.commit()
            raise NotFoundError("This account no longer exists.")

        if auth_user.is_banned:
            await self._repo.record_audit_event(
                event=AuthEvent.ACCESS_DENIED,
                outcome=AuthOutcome.FAILURE,
                user_id=claims.user_id,
                ip_address=context.ip_address,
                user_agent=context.user_agent,
                request_id=context.request_id,
                metadata={"reason": "account_banned"},
            )
            await self._repo.session.commit()
            # Kill outstanding tokens so the ban takes effect immediately rather
            # than at the end of the current token's 15-minute life.
            await revoke_user(claims.user_id, ttl_seconds=ACCESS_TOKEN_TTL_SECONDS)
            raise AccountBannedError(auth_user.ban_reason or AccountBannedError.message)

        role = _coerce_role(auth_user.role)
        profile = await self._repo.get_profile(claims.user_id)
        if profile is None:
            profile = await self._repo.upsert_profile(
                user_id=claims.user_id,
                role=role,
                display_name=auth_user.name,
            )
            logger.info("profile_provisioned", user_id=claims.user_id)
        elif profile.role is not role:
            # The identity service is authoritative; heal the local copy.
            await self._repo.sync_role_from_identity(user_id=claims.user_id, role=role)
            profile.role = role

        await self._repo.touch_last_active(claims.user_id, seen_at=datetime.now(UTC))
        await self._repo.session.commit()

        return AuthenticatedUser(claims=claims, profile=profile, auth_user=auth_user)

    def require_verified_email(self, user: AuthenticatedUser) -> None:
        """Gate a caller on email verification.

        Applied per-route rather than globally: an unverified user must still be
        able to read their own profile and re-request a verification email, or
        they are locked out of the very screens that fix the problem.
        """
        if not user.auth_user.email_verified:
            raise EmailNotVerifiedError()

    # ── Profile ──────────────────────────────────────────────────────────────

    def to_read_model(self, user: AuthenticatedUser) -> UserProfileRead:
        """Project a caller onto the public response schema."""
        profile = user.profile
        return UserProfileRead(
            user_id=profile.user_id,
            email=user.auth_user.email,
            email_verified=user.auth_user.email_verified,
            display_name=profile.display_name or user.auth_user.name,
            role=profile.role,
            institution=profile.institution,
            year_of_study=profile.year_of_study,
            specialization=profile.specialization,
            timezone=profile.timezone,
            locale=profile.locale,
            onboarding_completed=profile.onboarding_completed_at is not None,
            last_active_at=profile.last_active_at,
            created_at=profile.created_at,
        )

    async def update_profile(
        self,
        user: AuthenticatedUser,
        payload: UserProfileUpdate,
        context: RequestContext,
    ) -> UserProfileRead:
        """Apply a partial profile update for the caller.

        `exclude_unset` is the important detail: it distinguishes "field absent"
        from "field explicitly set to null", so a PATCH cannot accidentally wipe
        fields the client never mentioned.
        """
        changes: dict[str, Any] = payload.model_dump(exclude_unset=True)

        if changes and user.profile.onboarding_completed_at is None:
            # First successful profile edit completes onboarding.
            changes["onboarding_completed_at"] = datetime.now(UTC)

        updated = await self._repo.update_profile(user.user_id, changes)
        if updated is None:
            raise NotFoundError("Your profile could not be found.")

        await self._repo.record_audit_event(
            event=AuthEvent.PROFILE_UPDATE,
            outcome=AuthOutcome.SUCCESS,
            user_id=user.user_id,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            request_id=context.request_id,
            metadata={"fields": sorted(changes.keys())},
        )
        await self._repo.session.commit()

        return self.to_read_model(
            AuthenticatedUser(claims=user.claims, profile=updated, auth_user=user.auth_user)
        )

    # ── Revocation ───────────────────────────────────────────────────────────

    async def revoke_current_session(self, user: AuthenticatedUser, context: RequestContext) -> int:
        """Deny-list the caller's current session.

        Called by the web client on sign-out so the outstanding access token stops
        working immediately, instead of remaining valid for up to 15 minutes after
        Better Auth has already destroyed the cookie session.
        """
        session_id = user.claims.session_id
        if session_id:
            await revoke_session(session_id, ttl_seconds=ACCESS_TOKEN_TTL_SECONDS)
        else:
            # No session id in the token — the only safe scope is the whole user.
            await revoke_user(user.user_id, ttl_seconds=ACCESS_TOKEN_TTL_SECONDS)

        await self._repo.record_audit_event(
            event=AuthEvent.LOGOUT,
            outcome=AuthOutcome.SUCCESS,
            user_id=user.user_id,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            request_id=context.request_id,
            metadata={"scope": "session" if session_id else "user"},
        )
        await self._repo.session.commit()
        return ACCESS_TOKEN_TTL_SECONDS

    async def record_access_denied(
        self, user: AuthenticatedUser, context: RequestContext, *, required_role: str
    ) -> None:
        """Audit a failed authorization check."""
        await self._repo.record_audit_event(
            event=AuthEvent.ACCESS_DENIED,
            outcome=AuthOutcome.FAILURE,
            user_id=user.user_id,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            request_id=context.request_id,
            metadata={"required_role": required_role, "actual_role": user.role.value},
        )
        await self._repo.session.commit()


def _coerce_role(raw: str | None) -> UserRole:
    """Map the identity service's free-text role onto the application enum.

    Unknown values fall back to the least-privileged role. A typo in the identity
    provider must never grant access.
    """
    if raw is None:
        return UserRole.STUDENT
    try:
        return UserRole(raw.strip().lower())
    except ValueError:
        logger.warning("unknown_role_downgraded", raw_role=raw)
        return UserRole.STUDENT
