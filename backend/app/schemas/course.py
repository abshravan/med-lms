"""Request/response schemas for the course catalogue.

Note the deliberate split between what students see and what admins see. A
student's view of a course must never include draft lessons or internal
authoring fields, and the cleanest way to guarantee that is separate schemas
rather than conditional field stripping — a filter that can be forgotten is a
leak waiting to happen.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.course import ContentStatus, Difficulty, LessonContentType
from app.utils.slug import MAX_SLUG_LENGTH, slugify

# ── Shared field validators ──────────────────────────────────────────────────


def _clean_optional_text(value: str | None) -> str | None:
    """Trim whitespace and treat a blank string as absent."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class _SlugValidatorMixin(BaseModel):
    """Validates an explicitly supplied slug."""

    @field_validator("slug", check_fields=False)
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        """Reject a slug that is not already URL-safe.

        The value is *not* silently rewritten: if an author typed
        "Cardiology Basics" into a slug field, quietly storing
        `cardiology-basics` hides the transformation and makes the resulting URL
        a surprise. Slugs are auto-derived from the title when omitted; supplying
        one explicitly means taking responsibility for its shape.
        """
        if value is None:
            return None
        trimmed = value.strip().lower()
        if not trimmed:
            return None
        if slugify(trimmed) != trimmed:
            raise ValueError(
                "Use lowercase letters, numbers and single hyphens only "
                f"(suggested: '{slugify(trimmed)}')."
            )
        return trimmed


# ── Lessons ──────────────────────────────────────────────────────────────────


class LessonSummary(BaseModel):
    """A lesson as it appears inside a course outline."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    slug: str
    title: str
    summary: str | None
    content_type: LessonContentType
    duration_seconds: int | None
    is_free_preview: bool
    position: int


class LessonDetail(LessonSummary):
    """A single lesson, fetched directly."""

    course_id: uuid.UUID
    module_id: uuid.UUID
    status: ContentStatus
    published_at: datetime | None


class LessonCreate(_SlugValidatorMixin):
    """Create a lesson within a module."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=MAX_SLUG_LENGTH)
    summary: str | None = Field(default=None, max_length=2000)
    content_type: LessonContentType = LessonContentType.VIDEO
    duration_seconds: int | None = Field(default=None, gt=0, le=86_400)
    is_free_preview: bool = False

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Title cannot be blank.")
        return trimmed

    @field_validator("summary")
    @classmethod
    def _trim_summary(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class LessonUpdate(_SlugValidatorMixin):
    """Partially update a lesson.

    `position` is absent: ordering is changed only through the reorder endpoint,
    which rewrites a whole sibling set atomically. Allowing a position here would
    let a client create duplicates or gaps.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=MAX_SLUG_LENGTH)
    summary: str | None = Field(default=None, max_length=2000)
    content_type: LessonContentType | None = None
    duration_seconds: int | None = Field(default=None, gt=0, le=86_400)
    is_free_preview: bool | None = None

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Title cannot be blank.")
        return trimmed


# ── Modules ──────────────────────────────────────────────────────────────────


class ModuleRead(BaseModel):
    """A module and its visible lessons."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    title: str
    summary: str | None
    position: int
    lessons: list[LessonSummary]


class ModuleCreate(BaseModel):
    """Create a module within a course."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Title cannot be blank.")
        return trimmed

    @field_validator("summary")
    @classmethod
    def _trim_summary(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class ModuleUpdate(BaseModel):
    """Partially update a module."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Title cannot be blank.")
        return trimmed


# ── Courses ──────────────────────────────────────────────────────────────────


class CourseSummary(BaseModel):
    """A course as it appears in the catalogue list.

    Deliberately excludes the outline: a catalogue page showing 20 courses should
    not carry every lesson of every course.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None
    specialty: str | None
    difficulty: Difficulty
    status: ContentStatus
    cover_image_key: str | None
    lesson_count: int
    total_duration_seconds: int
    published_at: datetime | None


class CourseDetail(CourseSummary):
    """A course with its full outline."""

    description: str | None
    modules: list[ModuleRead]
    created_at: datetime
    updated_at: datetime


class CourseCreate(_SlugValidatorMixin):
    """Create a course. Always starts as a draft."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=MAX_SLUG_LENGTH)
    subtitle: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    specialty: str | None = Field(default=None, max_length=120)
    difficulty: Difficulty = Difficulty.FOUNDATION

    # `status` is absent by design. A course is created as a draft and moves
    # through the lifecycle only via the publish/archive endpoints, so there is no
    # path that creates already-published content without passing the publish
    # checks.

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Title cannot be blank.")
        return trimmed

    @field_validator("subtitle", "description", "specialty")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class CourseUpdate(_SlugValidatorMixin):
    """Partially update a course.

    `status` is absent here too — see `CourseCreate`.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=MAX_SLUG_LENGTH)
    subtitle: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    specialty: str | None = Field(default=None, max_length=120)
    difficulty: Difficulty | None = None
    cover_image_key: str | None = Field(default=None, max_length=512)

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Title cannot be blank.")
        return trimmed

    @field_validator("subtitle", "description", "specialty")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


# ── Ordering ─────────────────────────────────────────────────────────────────


class ReorderRequest(BaseModel):
    """Replace the order of a sibling set.

    The client sends **every** id in the group, in the desired order. A
    whole-set replacement rather than a "move item X to index N" operation,
    because it is idempotent, needs no conflict resolution when two admins reorder
    concurrently (last write wins, coherently), and cannot leave gaps or
    duplicates. The service rejects the request unless the ids exactly match the
    current members.
    """

    model_config = ConfigDict(extra="forbid")

    ordered_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)

    @field_validator("ordered_ids")
    @classmethod
    def _no_duplicates(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("The same id appears more than once.")
        return value


class OrderedItem(BaseModel):
    """An id and its resulting position, returned after a reorder."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    position: int


class ReorderResult(BaseModel):
    """The new ordering."""

    model_config = ConfigDict(extra="forbid")

    items: list[OrderedItem]


# ── Catalogue filters ────────────────────────────────────────────────────────


class CatalogueFilters(BaseModel):
    """Validated query parameters for the catalogue.

    Modelled rather than taken as loose `Query(...)` arguments so the rules live
    with the other schemas and are unit-testable without an HTTP client.
    """

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=120)
    specialty: str | None = Field(default=None, max_length=120)
    difficulty: Difficulty | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=512)

    @field_validator("q", "specialty")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)
