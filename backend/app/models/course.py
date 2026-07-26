"""Course catalogue models: courses → modules → lessons.

Two structural decisions are worth reading before changing anything here.

**1. A lesson's course cannot disagree with its module's course.**
`lessons` carries a denormalised `course_id` so that lesson lookups and the
future progress/bookmark tables can filter by course without a join. Denormalised
columns normally invite drift, so this one is made impossible to get wrong: the
foreign key is composite — `(module_id, course_id)` references
`modules(id, course_id)`. Postgres therefore rejects any lesson whose `course_id`
does not match its module's. The convenience is kept; the drift risk is removed.

**2. Ordering uses deferrable unique constraints.**
`UNIQUE (course_id, position)` guarantees no two modules claim the same slot.
Without `DEFERRABLE INITIALLY DEFERRED`, reordering would fail mid-statement the
moment two rows briefly shared a position. Deferring the check to `COMMIT` lets a
reorder rewrite every position in one transaction and still be validated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def _enum(enum_type: type[StrEnum], name: str) -> SAEnum:
    """Build a Postgres enum that stores the member *values*, not their names."""
    return SAEnum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


class ContentStatus(StrEnum):
    """Publication lifecycle.

    `archived` exists instead of deletion for courses: progress records, quiz
    attempts, and bookmarks will reference this content, and destroying a course
    would either orphan or cascade away a student's history.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Difficulty(StrEnum):
    """Course difficulty, in the vocabulary medical curricula actually use."""

    FOUNDATION = "foundation"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class LessonContentType(StrEnum):
    """What a lesson delivers.

    Present now so the catalogue can render the right affordance; the actual
    payloads arrive with the media (Feature 3) and notes (Feature 4) work.
    """

    VIDEO = "video"
    READING = "reading"
    QUIZ = "quiz"


class Course(Base, TimestampMixin):
    """A course: the top-level unit students enrol in and browse."""

    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Immutable once published — see CourseService.update. URLs and any external
    # links students have saved depend on it.
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    specialty: Mapped[str | None] = mapped_column(String(120), nullable=True)
    difficulty: Mapped[Difficulty] = mapped_column(
        _enum(Difficulty, "course_difficulty"),
        nullable=False,
        default=Difficulty.FOUNDATION,
        server_default=Difficulty.FOUNDATION.value,
    )
    status: Mapped[ContentStatus] = mapped_column(
        _enum(ContentStatus, "content_status"),
        nullable=False,
        default=ContentStatus.DRAFT,
        server_default=ContentStatus.DRAFT.value,
    )
    # Object key in Cloudflare R2. Populated by the media feature; the catalogue
    # renders a placeholder while it is null.
    cover_image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Nullable so an author's account can be removed without destroying content.
    created_by: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("user_profiles.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    modules: Mapped[list[Module]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Module.position",
    )

    __table_args__ = (
        # Required by the composite foreign key on `lessons` (see module docstring).
        UniqueConstraint("id", name="uq_courses_id"),
        CheckConstraint(
            "(status <> 'published') OR (published_at IS NOT NULL)",
            name="published_has_timestamp",
        ),
        # Covers the catalogue's default query: published courses, newest first.
        Index("ix_courses_status_published_at", "status", "published_at"),
        Index("ix_courses_specialty", "specialty"),
    )


class Module(Base, TimestampMixin):
    """An ordered section within a course."""

    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Zero-based and contiguous. The service layer is responsible for keeping it
    # gapless; the constraint below keeps it unique.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    course: Mapped[Course] = relationship(back_populates="modules")
    lessons: Mapped[list[Lesson]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="Lesson.position",
    )

    __table_args__ = (
        # Target of the composite FK from `lessons`.
        UniqueConstraint("id", "course_id", name="uq_modules_id_course_id"),
        UniqueConstraint(
            "course_id",
            "position",
            name="uq_modules_course_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_modules_course_id_position", "course_id", "position"),
    )


class Lesson(Base, TimestampMixin):
    """An ordered lesson within a module.

    Lessons have their own `status`: an author can add a lesson to a published
    course and keep it hidden until it is ready, without unpublishing the course.
    """

    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Denormalised, but kept honest by the composite FK below.
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Unique per course, not globally: two courses may both have an
    # "introduction" lesson, and the URL is scoped by course slug anyway.
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[LessonContentType] = mapped_column(
        _enum(LessonContentType, "lesson_content_type"),
        nullable=False,
        default=LessonContentType.VIDEO,
        server_default=LessonContentType.VIDEO.value,
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Lets prospective students sample a course before enrolling.
    is_free_preview: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[ContentStatus] = mapped_column(
        _enum(ContentStatus, "content_status"),
        nullable=False,
        default=ContentStatus.DRAFT,
        server_default=ContentStatus.DRAFT.value,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    module: Mapped[Module] = relationship(back_populates="lessons")

    __table_args__ = (
        # The constraint that makes the denormalised `course_id` trustworthy:
        # Postgres rejects any lesson whose course disagrees with its module's.
        ForeignKeyConstraint(
            ["module_id", "course_id"],
            ["modules.id", "modules.course_id"],
            name="fk_lessons_module_id_course_id_modules",
            ondelete="CASCADE",
        ),
        UniqueConstraint("course_id", "slug", name="uq_lessons_course_id_slug"),
        UniqueConstraint(
            "module_id",
            "position",
            name="uq_lessons_module_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0",
            name="duration_positive",
        ),
        Index("ix_lessons_module_id_position", "module_id", "position"),
        Index("ix_lessons_course_id_status", "course_id", "status"),
    )
