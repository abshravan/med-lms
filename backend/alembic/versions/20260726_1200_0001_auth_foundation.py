"""Auth foundation: user profiles and partitioned audit log.

Creates the application-owned side of authentication. The Better Auth tables in
the `auth` schema are NOT created here — they are owned by the `better-auth` CLI
and must already exist when this runs. See docs/features/authentication.md for
the required migration order.

Revision ID: 0001_auth_foundation
Revises:
Create Date: 2026-07-26 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_auth_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTH_SCHEMA = "auth"

# Monthly partitions pre-created for the audit log. Two years is enough runway
# that the maintenance job (see docs) has no urgency, while keeping the initial
# migration fast.
PARTITION_MONTHS = 24

USER_ROLE_VALUES = ("student", "admin")
AUTH_EVENT_VALUES = (
    "register",
    "login",
    "logout",
    "email_verify",
    "password_reset_request",
    "password_reset_complete",
    "token_rejected",
    "access_denied",
    "profile_update",
)
AUTH_OUTCOME_VALUES = ("success", "failure")


def _month_starts(count: int) -> list[tuple[date, date]]:
    """Return `count` consecutive (month_start, next_month_start) pairs.

    Starts at the first of the current month so the migration is deterministic
    regardless of the day it is applied.
    """
    today = date.today()
    year, month = today.year, today.month
    bounds: list[tuple[date, date]] = []
    for _ in range(count):
        start = date(year, month, 1)
        year_next, month_next = (year + 1, 1) if month == 12 else (year, month + 1)
        bounds.append((start, date(year_next, month_next, 1)))
        year, month = year_next, month_next
    return bounds


def _assert_identity_schema_present() -> None:
    """Fail early and legibly if Better Auth has not migrated yet.

    Without this, the failure surfaces as an opaque 'relation auth.user does not
    exist' from a foreign-key statement halfway through the migration.
    """
    exists = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = 'user')"
        ),
        {"schema": AUTH_SCHEMA},
    )
    if not exists:
        raise RuntimeError(
            f"Table {AUTH_SCHEMA}.user is missing. The Better Auth migration must run "
            "before Alembic. From the web workspace: `pnpm auth:migrate`, or run "
            "`./scripts/migrate.sh` from the repository root to do both in order."
        )


def upgrade() -> None:
    # Idempotent: the Docker init script normally creates this, but a managed
    # Postgres instance provisioned by hand will not have it.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {AUTH_SCHEMA}")
    _assert_identity_schema_present()

    user_role = postgresql.ENUM(*USER_ROLE_VALUES, name="user_role", create_type=False)
    auth_event = postgresql.ENUM(*AUTH_EVENT_VALUES, name="auth_event", create_type=False)
    auth_outcome = postgresql.ENUM(*AUTH_OUTCOME_VALUES, name="auth_outcome", create_type=False)

    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    auth_event.create(bind, checkfirst=True)
    auth_outcome.create(bind, checkfirst=True)

    # ── user_profiles ────────────────────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("role", user_role, server_default="student", nullable=False),
        sa.Column("institution", sa.String(length=200), nullable=True),
        sa.Column("year_of_study", sa.Integer(), nullable=True),
        sa.Column("specialization", sa.String(length=120), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("locale", sa.String(length=16), server_default="en", nullable=False),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_profiles"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{AUTH_SCHEMA}.user.id"],
            name="fk_user_profiles_user_id_user",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "year_of_study IS NULL OR (year_of_study >= 1 AND year_of_study <= 10)",
            name="ck_user_profiles_year_of_study_range",
        ),
    )
    op.create_index("ix_user_profiles_role", "user_profiles", ["role"])
    op.create_index("ix_user_profiles_last_active_at", "user_profiles", ["last_active_at"])

    # ── auth_audit_log (range-partitioned by month) ──────────────────────────
    # The primary key must include the partition key, hence (id, created_at).
    op.create_table(
        "auth_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("event", auth_event, nullable=False),
        sa.Column("outcome", auth_outcome, nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", "created_at", name="pk_auth_audit_log"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.create_index("ix_auth_audit_log_user_created", "auth_audit_log", ["user_id", "created_at"])
    op.create_index("ix_auth_audit_log_event_created", "auth_audit_log", ["event", "created_at"])

    for start, end in _month_starts(PARTITION_MONTHS):
        name = f"auth_audit_log_{start:%Y_%m}"
        op.execute(
            f"CREATE TABLE {name} PARTITION OF auth_audit_log "
            f"FOR VALUES FROM ('{start:%Y-%m-%d}') TO ('{end:%Y-%m-%d}')"
        )

    # Catch-all so an audit insert can never fail for want of a partition — an
    # audit write must not be able to break a sign-in. Caveat: attaching a new
    # monthly partition later requires the default partition to hold no rows in
    # that range, so the maintenance job must stay ahead. See docs.
    op.execute("CREATE TABLE auth_audit_log_default PARTITION OF auth_audit_log DEFAULT")


def downgrade() -> None:
    # Dropping the parent cascades to every partition.
    op.drop_table("auth_audit_log")
    op.drop_index("ix_user_profiles_last_active_at", table_name="user_profiles")
    op.drop_index("ix_user_profiles_role", table_name="user_profiles")
    op.drop_table("user_profiles")

    bind = op.get_bind()
    postgresql.ENUM(name="auth_outcome").drop(bind, checkfirst=True)
    postgresql.ENUM(name="auth_event").drop(bind, checkfirst=True)
    postgresql.ENUM(name="user_role").drop(bind, checkfirst=True)
