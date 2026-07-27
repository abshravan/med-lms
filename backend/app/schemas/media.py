"""Media upload and playback schemas.

The content-type allowlist and size ceilings live here rather than in the router,
so they are unit-testable without an HTTP client and cannot diverge between the
upload-request path and the confirmation path.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.media import MediaKind, MediaStatus

# ── Policy ───────────────────────────────────────────────────────────────────

ALLOWED_CONTENT_TYPES: dict[MediaKind, frozenset[str]] = {
    # Deliberately narrow. Every additional container is another decoder the
    # browser must expose to attacker-supplied bytes.
    MediaKind.LESSON_VIDEO: frozenset({"video/mp4", "video/webm", "video/quicktime"}),
    MediaKind.COURSE_COVER: frozenset({"image/jpeg", "image/png", "image/webp"}),
    # PDF only. Office formats carry macros, and students download these.
    MediaKind.LESSON_ATTACHMENT: frozenset({"application/pdf"}),
}

# Extension is derived from the *declared content type*, never from the client's
# filename — a file called `lecture.mp4.html` must not become an HTML object.
EXTENSION_BY_CONTENT_TYPE: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


# ── Requests ─────────────────────────────────────────────────────────────────


class UploadRequest(BaseModel):
    """Ask for a presigned upload URL."""

    model_config = ConfigDict(extra="forbid")

    kind: MediaKind
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=127)
    # Declared up front so an obviously oversized upload is rejected before the
    # bytes are sent, rather than after. The real size is still verified on
    # confirmation — this value is a courtesy, not a control.
    size_bytes: int = Field(gt=0)

    @field_validator("filename")
    @classmethod
    def _clean_filename(cls, value: str) -> str:
        """Strip any path component from the supplied filename.

        The filename is only ever echoed back in `Content-Disposition`; it never
        forms part of a storage key. Stripping directories anyway means a bug
        that later did use it cannot become a traversal.
        """
        trimmed = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
        if not trimmed or trimmed in {".", ".."}:
            raise ValueError("Filename is not valid.")
        return trimmed

    @field_validator("content_type")
    @classmethod
    def _normalise_content_type(cls, value: str) -> str:
        """Lower-case and drop any `; charset=` parameter."""
        return value.split(";")[0].strip().lower()


class UploadTicket(BaseModel):
    """Everything the client needs to perform the upload itself."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    upload_url: str
    method: str
    headers: dict[str, str]
    expires_in_seconds: int
    storage_key: str


class ConfirmUploadRequest(BaseModel):
    """Optional integrity data supplied after the client finishes uploading."""

    model_config = ConfigDict(extra="forbid")

    checksum: str | None = Field(default=None, max_length=128)


# ── Responses ────────────────────────────────────────────────────────────────


class MediaAssetRead(BaseModel):
    """An asset as the admin UI sees it."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    kind: MediaKind
    status: MediaStatus
    original_filename: str
    content_type: str
    size_bytes: int | None
    confirmed_at: datetime | None
    created_at: datetime


class PlaybackTicket(BaseModel):
    """A short-lived URL for viewing or downloading an asset."""

    model_config = ConfigDict(extra="forbid")

    url: str
    expires_in_seconds: int
    content_type: str
    # Present for video so the player can show a duration before metadata loads.
    duration_seconds: int | None = None


class AttachAssetRequest(BaseModel):
    """Attach an already-confirmed asset to a lesson or course."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
