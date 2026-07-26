"""Data access for the course catalogue."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Subquery, and_, func, or_, select, update
from sqlalchemy.orm import selectinload

from app.models.course import ContentStatus, Course, Difficulty, Lesson, Module
from app.repositories.base import BaseRepository
from app.utils.pagination import Cursor


class CourseRepository(BaseRepository[Course]):
    """Reads and writes courses, modules, and lessons."""

    model = Course

    # ── Catalogue reads ──────────────────────────────────────────────────────

    def _catalogue_counts(self) -> Subquery:
        """Per-course lesson count and total duration, over published lessons only.

        Computed on read rather than denormalised onto `courses`. Denormalised
        counters would need maintaining on every lesson insert, update, delete,
        publish, and reorder — five places to forget — and they drift silently
        when one is missed. Course counts are in the hundreds, not millions, and
        this aggregate runs against `ix_lessons_course_id_status`.

        Revisit if the catalogue query ever shows up in slow logs; the trigger is
        recorded in docs/features/courses.md.
        """
        return (
            select(
                Lesson.course_id.label("course_id"),
                func.count(Lesson.id).label("lesson_count"),
                func.coalesce(func.sum(Lesson.duration_seconds), 0).label("total_duration_seconds"),
            )
            .where(Lesson.status == ContentStatus.PUBLISHED)
            .group_by(Lesson.course_id)
            .subquery()
        )

    async def list_published(
        self,
        *,
        limit: int,
        cursor: Cursor | None = None,
        search: str | None = None,
        specialty: str | None = None,
        difficulty: Difficulty | None = None,
    ) -> tuple[list[tuple[Course, int, int]], bool]:
        """Return one page of the published catalogue, newest first.

        Fetches `limit + 1` rows to determine `has_more` without a second COUNT
        query — a count over the whole catalogue on every page request is pure
        waste when all the client needs is whether to show a "load more" button.

        Returns:
            The page as `(course, lesson_count, total_duration_seconds)` triples,
            and whether more rows exist beyond it.
        """
        counts = self._catalogue_counts()

        statement = (
            select(
                Course,
                func.coalesce(counts.c.lesson_count, 0),
                func.coalesce(counts.c.total_duration_seconds, 0),
            )
            .outerjoin(counts, counts.c.course_id == Course.id)
            .where(Course.status == ContentStatus.PUBLISHED)
        )

        if specialty is not None:
            statement = statement.where(Course.specialty == specialty)
        if difficulty is not None:
            statement = statement.where(Course.difficulty == difficulty)
        if search:
            # ILIKE with a leading wildcard cannot use a btree index. Acceptable
            # at catalogue scale; the upgrade path is a tsvector column with a GIN
            # index, noted as follow-up work.
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    Course.title.ilike(pattern),
                    Course.subtitle.ilike(pattern),
                    Course.specialty.ilike(pattern),
                )
            )

        if cursor is not None:
            # Keyset predicate over the same (published_at DESC, id DESC) ordering
            # the index provides. The `id` tiebreak makes the order total, so a
            # page boundary between two courses published in the same instant
            # cannot drop or repeat a row.
            statement = statement.where(
                or_(
                    Course.published_at < cursor.sort_value,
                    and_(
                        Course.published_at == cursor.sort_value,
                        Course.id < cursor.item_id,
                    ),
                )
            )

        statement = statement.order_by(Course.published_at.desc(), Course.id.desc()).limit(
            limit + 1
        )

        rows = (await self.session.execute(statement)).all()
        has_more = len(rows) > limit
        page = [(row[0], row[1], row[2]) for row in rows[:limit]]
        return page, has_more

    async def get_published_by_slug(self, slug: str) -> Course | None:
        """Load a published course with its outline, published lessons only.

        `selectinload` issues one additional query per relationship level rather
        than a join that multiplies rows — three queries total, no N+1, and no
        cartesian blow-up from joining modules to lessons.

        The lesson filter lives in the loader rather than in application code, so
        an unpublished lesson is never loaded into memory at all and cannot leak
        through a serialisation mistake.
        """
        statement = (
            select(Course)
            .where(Course.slug == slug, Course.status == ContentStatus.PUBLISHED)
            .options(
                selectinload(Course.modules).selectinload(
                    Module.lessons.and_(Lesson.status == ContentStatus.PUBLISHED)
                )
            )
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_published_lesson(self, *, course_slug: str, lesson_slug: str) -> Lesson | None:
        """Load a single published lesson within a published course."""
        statement = (
            select(Lesson)
            .join(Course, Course.id == Lesson.course_id)
            .where(
                Course.slug == course_slug,
                Course.status == ContentStatus.PUBLISHED,
                Lesson.slug == lesson_slug,
                Lesson.status == ContentStatus.PUBLISHED,
            )
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    # ── Admin reads ──────────────────────────────────────────────────────────

    async def list_all(
        self,
        *,
        limit: int,
        cursor: Cursor | None = None,
        status: ContentStatus | None = None,
    ) -> tuple[list[tuple[Course, int, int]], bool]:
        """Admin listing: every course regardless of status, newest created first."""
        counts = self._catalogue_counts()

        statement = select(
            Course,
            func.coalesce(counts.c.lesson_count, 0),
            func.coalesce(counts.c.total_duration_seconds, 0),
        ).outerjoin(counts, counts.c.course_id == Course.id)

        if status is not None:
            statement = statement.where(Course.status == status)
        if cursor is not None:
            statement = statement.where(
                or_(
                    Course.created_at < cursor.sort_value,
                    and_(
                        Course.created_at == cursor.sort_value,
                        Course.id < cursor.item_id,
                    ),
                )
            )

        statement = statement.order_by(Course.created_at.desc(), Course.id.desc()).limit(limit + 1)

        rows = (await self.session.execute(statement)).all()
        has_more = len(rows) > limit
        return [(row[0], row[1], row[2]) for row in rows[:limit]], has_more

    async def get_by_id(self, course_id: uuid.UUID) -> Course | None:
        """Load a course by id, no status filter. Admin use only."""
        return await self.session.get(Course, course_id)

    async def get_with_outline(self, course_id: uuid.UUID) -> Course | None:
        """Load a course with every module and lesson, drafts included."""
        statement = (
            select(Course)
            .where(Course.id == course_id)
            .options(selectinload(Course.modules).selectinload(Module.lessons))
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_by_slug_any_status(self, slug: str) -> Course | None:
        """Look up a course by slug regardless of status, for uniqueness checks."""
        statement = select(Course).where(Course.slug == slug)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def taken_course_slugs(self, prefix: str) -> set[str]:
        """Existing course slugs starting with `prefix`, for collision avoidance."""
        statement = select(Course.slug).where(Course.slug.like(f"{prefix}%"))
        return set((await self.session.execute(statement)).scalars().all())

    async def taken_lesson_slugs(self, course_id: uuid.UUID, prefix: str) -> set[str]:
        """Existing lesson slugs in a course starting with `prefix`."""
        statement = select(Lesson.slug).where(
            Lesson.course_id == course_id, Lesson.slug.like(f"{prefix}%")
        )
        return set((await self.session.execute(statement)).scalars().all())

    # ── Modules and lessons ──────────────────────────────────────────────────

    async def get_module(self, module_id: uuid.UUID) -> Module | None:
        """Load a module by id."""
        return await self.session.get(Module, module_id)

    async def get_module_with_lessons(self, module_id: uuid.UUID) -> Module | None:
        """Load a module with its lessons ordered by position."""
        statement = (
            select(Module).where(Module.id == module_id).options(selectinload(Module.lessons))
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_lesson(self, lesson_id: uuid.UUID) -> Lesson | None:
        """Load a lesson by id."""
        return await self.session.get(Lesson, lesson_id)

    async def get_lesson_with_course(self, lesson_id: uuid.UUID) -> tuple[Lesson, Course] | None:
        """Load a lesson together with its course, in one round-trip."""
        statement = (
            select(Lesson, Course)
            .join(Course, Course.id == Lesson.course_id)
            .where(Lesson.id == lesson_id)
        )
        row = (await self.session.execute(statement)).first()
        return (row[0], row[1]) if row is not None else None

    async def next_module_position(self, course_id: uuid.UUID) -> int:
        """The position a newly appended module should take."""
        statement = select(func.coalesce(func.max(Module.position), -1) + 1).where(
            Module.course_id == course_id
        )
        return int((await self.session.execute(statement)).scalar_one())

    async def next_lesson_position(self, module_id: uuid.UUID) -> int:
        """The position a newly appended lesson should take."""
        statement = select(func.coalesce(func.max(Lesson.position), -1) + 1).where(
            Lesson.module_id == module_id
        )
        return int((await self.session.execute(statement)).scalar_one())

    async def module_ids_for_course(self, course_id: uuid.UUID) -> list[uuid.UUID]:
        """Every module id in a course, in current order."""
        statement = select(Module.id).where(Module.course_id == course_id).order_by(Module.position)
        return list((await self.session.execute(statement)).scalars().all())

    async def lesson_ids_for_module(self, module_id: uuid.UUID) -> list[uuid.UUID]:
        """Every lesson id in a module, in current order."""
        statement = select(Lesson.id).where(Lesson.module_id == module_id).order_by(Lesson.position)
        return list((await self.session.execute(statement)).scalars().all())

    async def apply_module_order(self, ordered_ids: list[uuid.UUID]) -> None:
        """Rewrite module positions to match the supplied order.

        Safe as a plain sequence of UPDATEs because
        `uq_modules_course_id_position` is `DEFERRABLE INITIALLY DEFERRED`:
        uniqueness is checked once at COMMIT, so the transient states where two
        modules share a position mid-rewrite are legal.
        """
        for position, module_id in enumerate(ordered_ids):
            await self.session.execute(
                update(Module).where(Module.id == module_id).values(position=position)
            )

    async def apply_lesson_order(self, ordered_ids: list[uuid.UUID]) -> None:
        """Rewrite lesson positions to match the supplied order."""
        for position, lesson_id in enumerate(ordered_ids):
            await self.session.execute(
                update(Lesson).where(Lesson.id == lesson_id).values(position=position)
            )

    async def publish_all_lessons(self, course_id: uuid.UUID, *, at: datetime) -> int:
        """Publish every draft lesson in a course. Returns the number changed."""
        # `execute` is typed as returning `Result`, but an UPDATE always yields a
        # `CursorResult` at runtime — which is the only variant carrying rowcount.
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(Lesson)
                .where(Lesson.course_id == course_id, Lesson.status == ContentStatus.DRAFT)
                .values(status=ContentStatus.PUBLISHED, published_at=at)
            ),
        )
        return int(result.rowcount or 0)

    async def count_published_lessons(self, course_id: uuid.UUID) -> int:
        """How many lessons in a course are publishable/published."""
        statement = select(func.count(Lesson.id)).where(
            Lesson.course_id == course_id, Lesson.status == ContentStatus.PUBLISHED
        )
        return int((await self.session.execute(statement)).scalar_one())

    async def count_lessons(self, course_id: uuid.UUID) -> int:
        """Total lessons in a course, any status."""
        statement = select(func.count(Lesson.id)).where(Lesson.course_id == course_id)
        return int((await self.session.execute(statement)).scalar_one())

    def add(self, instance: Course | Module | Lesson) -> None:
        """Stage a new entity. The service owns the commit."""
        self.session.add(instance)

    async def delete(self, instance: Module | Lesson) -> None:
        """Delete a module or lesson.

        Courses are archived rather than deleted — see `ContentStatus`.
        """
        await self.session.delete(instance)
