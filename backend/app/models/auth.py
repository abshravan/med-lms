"""Read-only mappings of the Better Auth tables.

These tables live in the `auth` schema and are created and migrated by the
`better-auth` CLI in the Next.js app. They are mapped here **only so the domain
API can read identity data in a join**.

Hard rules, enforced by review and by the Alembic filter:

* The API never INSERTs, UPDATEs, or DELETEs these rows. All identity mutation
  goes through Better Auth's own endpoints.
* Only the narrow, stable column surface below is mapped. Product-specific
  fields belong in `public.user_profiles`, which the application owns outright.

See docs/architecture.md §5.1 for the ownership rationale.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EXTERNALLY_MANAGED, Base

AUTH_SCHEMA = "auth"


class AuthUser(Base):
    """The Better Auth `user` table. Read-only from this service."""

    __tablename__ = "user"
    __table_args__ = {"schema": AUTH_SCHEMA, "info": {EXTERNALLY_MANAGED: True}}

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    email_verified: Mapped[bool] = mapped_column(
        "emailVerified", Boolean, nullable=False, default=False
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    banned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ban_reason: Mapped[str | None] = mapped_column("banReason", String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", DateTime(timezone=True), nullable=False
    )

    @property
    def is_banned(self) -> bool:
        """Normalise the nullable `banned` column to a definite boolean."""
        return bool(self.banned)
