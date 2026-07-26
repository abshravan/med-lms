"""Data access for identity and profile records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.auth import AuthUser
from app.models.profile import (
    AuthAuditLog,
    AuthEvent,
    AuthOutcome,
    UserProfile,
    UserRole,
)
from app.repositories.base import BaseRepository

# How stale `last_active_at` may get before we bother writing it again. Writing on
# every request would put an UPDATE on the hot path of literally every
# authenticated call for a field nothing reads in real time.
LAST_ACTIVE_WRITE_THRESHOLD = timedelta(minutes=5)


class UserRepository(BaseRepository[UserProfile]):
    """Reads identity data and owns the `user_profiles` table."""

    model = UserProfile

    async def get_auth_user(self, user_id: str) -> AuthUser | None:
        """Load the Better Auth user row. Read-only."""
        result = await self.session.execute(select(AuthUser).where(AuthUser.id == user_id))
        return result.scalar_one_or_none()

    async def get_profile(self, user_id: str) -> UserProfile | None:
        """Load a profile by user id."""
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_profile_with_auth_user(self, user_id: str) -> tuple[UserProfile, AuthUser] | None:
        """Load profile and identity row in a single round-trip."""
        result = await self.session.execute(
            select(UserProfile, AuthUser)
            .join(AuthUser, AuthUser.id == UserProfile.user_id)
            .where(UserProfile.user_id == user_id)
        )
        row = result.first()
        if row is None:
            return None
        return row[0], row[1]

    async def upsert_profile(
        self,
        *,
        user_id: str,
        role: UserRole,
        display_name: str | None,
    ) -> UserProfile:
        """Create the profile if absent, otherwise return the existing row.

        `ON CONFLICT DO UPDATE` on a no-op column rather than
        `DO NOTHING`, because `DO NOTHING` returns no row on conflict and would
        force a second SELECT. Two concurrent first-requests from the same user
        (a real race on a dashboard that fires several queries at once) both get a
        row back without either failing.

        `role` is only applied on insert — see the excluded columns below — so
        this can never silently downgrade an admin.
        """
        statement = (
            pg_insert(UserProfile)
            .values(user_id=user_id, role=role.value, display_name=display_name)
            .on_conflict_do_update(
                index_elements=[UserProfile.user_id],
                set_={"updated_at": datetime.now(UTC)},
            )
            .returning(UserProfile)
        )
        result = await self.session.execute(statement)
        return result.scalar_one()

    async def update_profile(self, user_id: str, changes: dict[str, Any]) -> UserProfile | None:
        """Apply a partial update and return the updated row.

        An empty `changes` dict is treated as a read, not as an error: a PATCH
        with no effective changes is idempotent and should succeed.
        """
        if not changes:
            return await self.get_profile(user_id)

        result = await self.session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(**changes)
            .returning(UserProfile)
        )
        return result.scalar_one_or_none()

    async def sync_role_from_identity(self, *, user_id: str, role: UserRole) -> None:
        """Mirror the authoritative role from the identity service.

        The identity service owns `role`; this keeps the local copy usable for
        joins and analytics without making it the source of truth.
        """
        await self.session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id, UserProfile.role != role.value)
            .values(role=role.value)
        )

    async def touch_last_active(self, user_id: str, *, seen_at: datetime) -> None:
        """Record activity, but only if the stored value is meaningfully stale."""
        cutoff = seen_at - LAST_ACTIVE_WRITE_THRESHOLD
        await self.session.execute(
            update(UserProfile)
            .where(
                UserProfile.user_id == user_id,
                (UserProfile.last_active_at.is_(None)) | (UserProfile.last_active_at < cutoff),
            )
            .values(last_active_at=seen_at)
        )

    async def record_audit_event(
        self,
        *,
        event: AuthEvent,
        outcome: AuthOutcome,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Append a row to the audit trail."""
        self.session.add(
            AuthAuditLog(
                user_id=user_id,
                event=event,
                outcome=outcome,
                ip_address=ip_address,
                user_agent=user_agent[:512] if user_agent else None,
                request_id=request_id,
                event_metadata=metadata,
            )
        )
