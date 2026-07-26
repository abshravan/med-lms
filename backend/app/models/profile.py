"""Application-owned identity tables.

`user_profiles` is the join point every future feature hangs off: progress,
bookmarks, quiz attempts, and viva sessions all foreign-key to `user_id` here
rather than to the Better Auth table, so a change in the identity provider never
cascades through the domain schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.auth import AUTH_SCHEMA
from app.models.base import Base, TimestampMixin


class UserRole(StrEnum):
    """Application roles.

    Mirrored from the Better Auth `user.role` column. Kept as a database enum so
    an invalid role cannot be persisted even by a direct SQL write.
    """

    STUDENT = "student"
    ADMIN = "admin"


class AuthEvent(StrEnum):
    """Auditable authentication events."""

    REGISTER = "register"
    LOGIN = "login"
    LOGOUT = "logout"
    EMAIL_VERIFY = "email_verify"
    PASSWORD_RESET_REQUEST = "password_reset_request"  # noqa: S105 - an event name, not a credential
    PASSWORD_RESET_COMPLETE = "password_reset_complete"  # noqa: S105 - an event name, not a credential
    TOKEN_REJECTED = "token_rejected"  # noqa: S105 - an event name, not a credential
    ACCESS_DENIED = "access_denied"
    PROFILE_UPDATE = "profile_update"


class AuthOutcome(StrEnum):
    """Whether the audited event succeeded."""

    SUCCESS = "success"
    FAILURE = "failure"


class UserProfile(Base, TimestampMixin):
    """Product-specific profile data for an authenticated user.

    One row per `auth.user`, created lazily on first authenticated request
    (see `AuthService.get_or_create_profile`) rather than by a hook in the
    identity service. That keeps profile creation resilient: a user who signed up
    while this API was down still gets a profile the moment they use it.
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{AUTH_SCHEMA}.user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserRole.STUDENT,
        server_default=UserRole.STUDENT.value,
    )
    institution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    year_of_study: Mapped[int | None] = mapped_column(Integer, nullable=True)
    specialization: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    locale: Mapped[str] = mapped_column(
        String(16), nullable=False, default="en", server_default="en"
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "year_of_study IS NULL OR (year_of_study >= 1 AND year_of_study <= 10)",
            name="year_of_study_range",
        ),
        Index("ix_user_profiles_role", "role"),
        Index("ix_user_profiles_last_active_at", "last_active_at"),
    )


class AuthAuditLog(Base):
    """Append-only audit trail of authentication-relevant events.

    Written by both services: Better Auth database hooks record sign-up / sign-in
    / reset, and this API records token rejections, denied access, and profile
    changes. The table is owned by Alembic; both are permitted writers.

    Range-partitioned by month from day one. At 100k users this reaches roughly
    12M rows/year, and retrofitting partitioning onto a table that size is a
    downtime migration — see docs/architecture.md §5.3.
    """

    __tablename__ = "auth_audit_log"

    # A partitioned table's primary key must contain the partition key, hence the
    # composite (id, created_at).
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        nullable=False,
    )
    # Intentionally *not* a foreign key: audit rows must survive user deletion,
    # and failed events may reference an email that never became a user.
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event: Mapped[AuthEvent] = mapped_column(
        SAEnum(AuthEvent, name="auth_event", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    outcome: Mapped[AuthOutcome] = mapped_column(
        SAEnum(AuthOutcome, name="auth_outcome", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Never store credentials or tokens here — only non-sensitive context such as
    # the reason a token was rejected.
    event_metadata: Mapped[dict[str, object] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    __table_args__ = (
        Index("ix_auth_audit_log_user_created", "user_id", "created_at"),
        Index("ix_auth_audit_log_event_created", "event", "created_at"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )
