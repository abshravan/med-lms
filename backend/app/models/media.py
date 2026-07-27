"""Media asset model.

An asset row is created **before** the bytes exist: the API issues a presigned
URL and records its intent, then the client uploads directly to storage and calls
back to confirm. That means `status` is not decoration — it is the only thing
distinguishing "we promised a URL and nothing happened" from "there is a real
object behind this row".

Confirmation is not taken on trust. The service HEADs the object in storage
before marking an asset ready, so a client that skips the upload and calls
confirm anyway gets a 409 rather than a lesson pointing at nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _enum(enum_type: type[StrEnum], name: str) -> SAEnum:
    """Build a Postgres enum storing member values rather than names."""
    return SAEnum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


class MediaKind(StrEnum):
    """What an asset is for.

    Determines the accepted content types and the size ceiling, so a cover image
    cannot be used to smuggle in a 2 GB upload.
    """

    LESSON_VIDEO = "lesson_video"
    COURSE_COVER = "course_cover"
    LESSON_ATTACHMENT = "lesson_attachment"


class MediaStatus(StrEnum):
    """Upload lifecycle.

    `pending` → a presigned URL was issued; bytes may or may not exist.
    `ready`   → the object was verified present in storage.
    `failed`  → confirmation found the object missing, oversized, or mistyped.
    """

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class MediaAsset(Base, TimestampMixin):
    """A single object in storage, plus the metadata the app needs about it."""

    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    kind: Mapped[MediaKind] = mapped_column(_enum(MediaKind, "media_kind"), nullable=False)
    status: Mapped[MediaStatus] = mapped_column(
        _enum(MediaStatus, "media_status"),
        nullable=False,
        default=MediaStatus.PENDING,
        server_default=MediaStatus.PENDING.value,
    )

    # Server-generated, never supplied by a client — see MediaService.build_key.
    # Unique so a retried upload cannot silently overwrite a confirmed asset.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)

    # Kept only to restore a sensible download filename; never used to build a path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)

    # Declared by the client at request time, replaced with the real value from
    # storage on confirmation. BigInteger because a 4 GB lecture overflows int4.
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    uploaded_by: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("user_profiles.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_non_negative"),
        # A ready asset without a confirmation timestamp would mean the verify
        # step was bypassed.
        CheckConstraint(
            "(status <> 'ready') OR (confirmed_at IS NOT NULL AND size_bytes IS NOT NULL)",
            name="ready_is_confirmed",
        ),
        # Serves the orphan-cleanup job: pending assets older than the presign TTL
        # were abandoned mid-upload.
        Index("ix_media_assets_status_created_at", "status", "created_at"),
        Index("ix_media_assets_uploaded_by", "uploaded_by"),
    )

    @property
    def is_ready(self) -> bool:
        return self.status is MediaStatus.READY
