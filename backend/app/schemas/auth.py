"""Request/response schemas for the auth feature.

These are the API contract. They are deliberately separate from the ORM models:
a schema change is a client-visible event, a model change is not, and conflating
them is how internal columns leak into public payloads.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.profile import UserRole


class UserProfileRead(BaseModel):
    """The authenticated user, as the client sees them."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    user_id: str
    email: str
    email_verified: bool
    display_name: str | None
    role: UserRole
    institution: str | None
    year_of_study: int | None
    specialization: str | None
    timezone: str
    locale: str
    onboarding_completed: bool
    last_active_at: datetime | None
    created_at: datetime


class UserProfileUpdate(BaseModel):
    """Partial update of the caller's own profile.

    Every field is optional; only those present in the request body are applied,
    so a client can PATCH one field without echoing the whole object back.

    Note the omissions: `email`, `email_verified`, and `role` are **not** here.
    Email changes go through Better Auth (they require re-verification) and role
    changes are an admin operation. Leaving them out of the schema means a
    privilege-escalation attempt fails validation before reaching any logic.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    institution: str | None = Field(default=None, max_length=200)
    year_of_study: int | None = Field(default=None, ge=1, le=10)
    specialization: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    locale: str | None = Field(default=None, min_length=2, max_length=16)

    @field_validator("display_name", "institution", "specialization", "timezone", "locale")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        """Trim surrounding whitespace and treat a blank string as absent."""
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        """Reject anything that is not a real IANA zone.

        Validated here rather than on read, because a bad zone silently breaks
        every future scheduled-reminder and analytics-bucketing feature.
        """
        if value is None:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"'{value}' is not a recognised IANA timezone.") from exc
        return value


class SessionRevokeRequest(BaseModel):
    """Ask the API to deny-list a session id before its token expires."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=255)


class RevocationResult(BaseModel):
    """Outcome of a revocation request."""

    model_config = ConfigDict(extra="forbid")

    revoked: bool
    expires_in_seconds: int = Field(
        description="How long the deny-list entry is held — the access-token TTL."
    )


class AuthDiagnostics(BaseModel):
    """Non-sensitive view of the caller's token, for client debugging.

    Deliberately excludes the raw token and every claim not listed. Useful when a
    student reports "it says I'm logged out" and support needs to know which
    session and role the API actually saw.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: str
    session_id: str | None
    email_verified: bool
    expires_at: datetime
    seconds_until_expiry: int
