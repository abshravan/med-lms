"""Course catalogue business logic.

This service owns the publication lifecycle and the transaction boundary for
every catalogue mutation. The rules enforced here — not in routers, not in the
database — are:

* A course is created as a draft and reaches `published` only through `publish()`.
* A published course's slug is immutable: students bookmark and share these URLs.
* Publishing requires at least one lesson, so a published course is never empty.
* Reordering replaces an entire sibling set and must name exactly its members.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.course import ContentStatus, Course, Lesson, Module
from app.repositories.course_repository import CourseRepository
from app.schemas.common import Page, PaginationMeta
from app.schemas.course import (
    CatalogueFilters,
    CourseCreate,
    CourseDetail,
    CourseSummary,
    CourseUpdate,
    LessonCreate,
    LessonDetail,
    LessonSummary,
    LessonUpdate,
    ModuleCreate,
    ModuleRead,
    ModuleUpdate,
    OrderedItem,
    ReorderResult,
)
from app.utils.pagination import clamp_limit, decode_cursor, encode_cursor
from app.utils.slug import slugify, unique_slug

logger = get_logger(__name__)


class CourseService:
    """Catalogue use cases. One instance per request."""

    def __init__(self, repository: CourseRepository) -> None:
        self._repo = repository

    # ── Student-facing reads ─────────────────────────────────────────────────

    async def list_catalogue(self, filters: CatalogueFilters) -> Page[CourseSummary]:
        """Return one page of the published catalogue."""
        limit = clamp_limit(filters.limit)
        cursor = decode_cursor(filters.cursor) if filters.cursor else None

        rows, has_more = await self._repo.list_published(
            limit=limit,
            cursor=cursor,
            search=filters.q,
            specialty=filters.specialty,
            difficulty=filters.difficulty,
        )

        items = [
            self._to_summary(course, lesson_count, duration)
            for course, lesson_count, duration in rows
        ]

        next_cursor: str | None = None
        if has_more and rows:
            last_course = rows[-1][0]
            # Published courses always have `published_at` — enforced by
            # ck_courses_published_has_timestamp — so this is not None here.
            if last_course.published_at is not None:
                next_cursor = encode_cursor(last_course.published_at, last_course.id)

        return Page(
            items=items,
            pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def get_course(self, slug: str) -> CourseDetail:
        """Load a published course with its outline.

        Raises:
            NotFoundError: No published course with that slug. A draft or archived
                course is reported as not-found rather than forbidden, so the
                endpoint cannot be used to discover unreleased content.
        """
        course = await self._repo.get_published_by_slug(slug)
        if course is None:
            raise NotFoundError("That course could not be found.")
        return self._to_detail(course)

    async def get_lesson(self, *, course_slug: str, lesson_slug: str) -> LessonDetail:
        """Load a single published lesson."""
        lesson = await self._repo.get_published_lesson(
            course_slug=course_slug, lesson_slug=lesson_slug
        )
        if lesson is None:
            raise NotFoundError("That lesson could not be found.")
        return LessonDetail.model_validate(lesson)

    # ── Admin reads ──────────────────────────────────────────────────────────

    async def list_all_courses(
        self, *, limit: int, cursor: str | None, status: ContentStatus | None
    ) -> Page[CourseSummary]:
        """Admin listing, including drafts and archived courses."""
        page_size = clamp_limit(limit)
        decoded = decode_cursor(cursor) if cursor else None

        rows, has_more = await self._repo.list_all(limit=page_size, cursor=decoded, status=status)
        items = [
            self._to_summary(course, lesson_count, duration)
            for course, lesson_count, duration in rows
        ]

        next_cursor: str | None = None
        if has_more and rows:
            last = rows[-1][0]
            next_cursor = encode_cursor(last.created_at, last.id)

        return Page(
            items=items,
            pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=page_size),
        )

    async def get_course_for_admin(self, course_id: uuid.UUID) -> CourseDetail:
        """Load a course with its full outline, drafts included."""
        course = await self._repo.get_with_outline(course_id)
        if course is None:
            raise NotFoundError("That course could not be found.")
        return self._to_detail(course)

    # ── Course authoring ─────────────────────────────────────────────────────

    async def create_course(self, payload: CourseCreate, *, author_id: str) -> CourseDetail:
        """Create a draft course."""
        slug = await self._resolve_course_slug(payload.slug, payload.title)

        course = Course(
            slug=slug,
            title=payload.title,
            subtitle=payload.subtitle,
            description=payload.description,
            specialty=payload.specialty,
            difficulty=payload.difficulty,
            status=ContentStatus.DRAFT,
            created_by=author_id,
        )
        self._repo.add(course)
        await self._commit_or_conflict("A course with that slug already exists.")

        logger.info("course_created", course_id=str(course.id), slug=course.slug)
        return self._to_detail(course, modules=[])

    async def update_course(self, course_id: uuid.UUID, payload: CourseUpdate) -> CourseDetail:
        """Partially update a course."""
        course = await self._repo.get_by_id(course_id)
        if course is None:
            raise NotFoundError("That course could not be found.")

        changes = payload.model_dump(exclude_unset=True)

        if "slug" in changes and changes["slug"] is not None:
            new_slug = changes["slug"]
            if new_slug != course.slug and course.status is ContentStatus.PUBLISHED:
                # Changing a live URL breaks every bookmark and inbound link. If
                # this is ever genuinely needed it should be a redirect table, not
                # a silent rename.
                raise ConflictError(
                    "A published course's slug cannot be changed, because existing "
                    "links would stop working."
                )
        elif "slug" in changes:
            # An explicit null means "leave it alone", not "clear it".
            changes.pop("slug")

        for field, value in changes.items():
            setattr(course, field, value)

        await self._commit_or_conflict("A course with that slug already exists.")

        refreshed = await self._repo.get_with_outline(course.id)
        return self._to_detail(refreshed or course)

    async def publish_course(self, course_id: uuid.UUID) -> CourseDetail:
        """Publish a course and everything currently drafted inside it.

        Publishing cascades to lessons deliberately: an author who has finished a
        course expects "publish" to make it visible, not to leave every lesson
        individually hidden. Lessons can still be unpublished afterwards.

        Raises:
            ValidationError: The course has no lessons. A published course with an
                empty outline is a broken landing page, so this is blocked at the
                point of publication rather than discovered by a student.
        """
        course = await self._repo.get_by_id(course_id)
        if course is None:
            raise NotFoundError("That course could not be found.")

        if course.status is ContentStatus.PUBLISHED:
            refreshed = await self._repo.get_with_outline(course.id)
            return self._to_detail(refreshed or course)

        lesson_count = await self._repo.count_lessons(course_id)
        if lesson_count == 0:
            raise ValidationError(
                "Add at least one lesson before publishing this course.",
                details=[{"field": "lessons", "message": "A course must contain a lesson."}],
            )

        now = datetime.now(UTC)
        course.status = ContentStatus.PUBLISHED
        course.published_at = now
        published = await self._repo.publish_all_lessons(course_id, at=now)

        await self._repo.session.commit()
        logger.info(
            "course_published",
            course_id=str(course.id),
            lessons_published=published,
        )

        refreshed = await self._repo.get_with_outline(course.id)
        return self._to_detail(refreshed or course)

    async def archive_course(self, course_id: uuid.UUID) -> CourseDetail:
        """Archive a course, removing it from the catalogue.

        `published_at` is preserved so republishing keeps the original date, and
        so analytics over historical content still work.
        """
        course = await self._repo.get_by_id(course_id)
        if course is None:
            raise NotFoundError("That course could not be found.")

        course.status = ContentStatus.ARCHIVED
        await self._repo.session.commit()
        logger.info("course_archived", course_id=str(course.id))

        refreshed = await self._repo.get_with_outline(course.id)
        return self._to_detail(refreshed or course)

    # ── Modules ──────────────────────────────────────────────────────────────

    async def create_module(self, course_id: uuid.UUID, payload: ModuleCreate) -> ModuleRead:
        """Append a module to a course."""
        course = await self._repo.get_by_id(course_id)
        if course is None:
            raise NotFoundError("That course could not be found.")

        module = Module(
            course_id=course_id,
            title=payload.title,
            summary=payload.summary,
            position=await self._repo.next_module_position(course_id),
        )
        self._repo.add(module)
        await self._commit_or_conflict("That module position is already taken.")

        return ModuleRead(
            id=module.id,
            title=module.title,
            summary=module.summary,
            position=module.position,
            lessons=[],
        )

    async def update_module(self, module_id: uuid.UUID, payload: ModuleUpdate) -> ModuleRead:
        """Partially update a module."""
        module = await self._repo.get_module_with_lessons(module_id)
        if module is None:
            raise NotFoundError("That module could not be found.")

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(module, field, value)

        await self._repo.session.commit()
        return self._to_module_read(module)

    async def delete_module(self, module_id: uuid.UUID) -> None:
        """Delete a module and its lessons, then close the position gap.

        Unlike courses, modules are hard-deleted: they are organisational
        containers, and nothing outside the catalogue references them.
        """
        module = await self._repo.get_module(module_id)
        if module is None:
            raise NotFoundError("That module could not be found.")

        course_id = module.course_id
        await self._repo.delete(module)
        await self._repo.session.flush()

        # Renumber so positions stay contiguous; a gap would make the next
        # append land on an unexpected index.
        remaining = await self._repo.module_ids_for_course(course_id)
        await self._repo.apply_module_order(remaining)
        await self._repo.session.commit()

    async def reorder_modules(
        self, course_id: uuid.UUID, ordered_ids: list[uuid.UUID]
    ) -> ReorderResult:
        """Replace the module order for a course."""
        course = await self._repo.get_by_id(course_id)
        if course is None:
            raise NotFoundError("That course could not be found.")

        current = await self._repo.module_ids_for_course(course_id)
        self._assert_same_members(current, ordered_ids, noun="module")

        await self._repo.apply_module_order(ordered_ids)
        await self._repo.session.commit()

        return ReorderResult(
            items=[
                OrderedItem(id=item_id, position=index) for index, item_id in enumerate(ordered_ids)
            ]
        )

    # ── Lessons ──────────────────────────────────────────────────────────────

    async def create_lesson(self, module_id: uuid.UUID, payload: LessonCreate) -> LessonDetail:
        """Append a lesson to a module."""
        module = await self._repo.get_module(module_id)
        if module is None:
            raise NotFoundError("That module could not be found.")

        slug = await self._resolve_lesson_slug(module.course_id, payload.slug, payload.title)

        lesson = Lesson(
            module_id=module_id,
            # Set from the module rather than taken from the client. The composite
            # foreign key would reject a mismatch anyway, but deriving it means the
            # client cannot even express the wrong thing.
            course_id=module.course_id,
            slug=slug,
            title=payload.title,
            summary=payload.summary,
            content_type=payload.content_type,
            duration_seconds=payload.duration_seconds,
            is_free_preview=payload.is_free_preview,
            status=ContentStatus.DRAFT,
            position=await self._repo.next_lesson_position(module_id),
        )
        self._repo.add(lesson)
        await self._commit_or_conflict("A lesson with that slug already exists in this course.")

        return LessonDetail.model_validate(lesson)

    async def update_lesson(self, lesson_id: uuid.UUID, payload: LessonUpdate) -> LessonDetail:
        """Partially update a lesson."""
        found = await self._repo.get_lesson_with_course(lesson_id)
        if found is None:
            raise NotFoundError("That lesson could not be found.")
        lesson, _course = found

        changes = payload.model_dump(exclude_unset=True)

        if "slug" in changes:
            if changes["slug"] is None:
                changes.pop("slug")
            elif changes["slug"] != lesson.slug and lesson.status is ContentStatus.PUBLISHED:
                raise ConflictError(
                    "A published lesson's slug cannot be changed, because existing "
                    "links would stop working."
                )

        for field, value in changes.items():
            setattr(lesson, field, value)

        await self._commit_or_conflict("A lesson with that slug already exists in this course.")
        return LessonDetail.model_validate(lesson)

    async def set_lesson_status(self, lesson_id: uuid.UUID, *, publish: bool) -> LessonDetail:
        """Publish or unpublish a single lesson.

        Publishing a lesson inside a draft course is allowed — it simply stays
        invisible until the course itself is published. Blocking it would force
        authors to sequence their work around the system's constraints rather
        than their own.
        """
        lesson = await self._repo.get_lesson(lesson_id)
        if lesson is None:
            raise NotFoundError("That lesson could not be found.")

        if publish:
            lesson.status = ContentStatus.PUBLISHED
            lesson.published_at = lesson.published_at or datetime.now(UTC)
        else:
            lesson.status = ContentStatus.DRAFT

        await self._repo.session.commit()
        return LessonDetail.model_validate(lesson)

    async def delete_lesson(self, lesson_id: uuid.UUID) -> None:
        """Delete a lesson and close the position gap."""
        lesson = await self._repo.get_lesson(lesson_id)
        if lesson is None:
            raise NotFoundError("That lesson could not be found.")

        module_id = lesson.module_id
        await self._repo.delete(lesson)
        await self._repo.session.flush()

        remaining = await self._repo.lesson_ids_for_module(module_id)
        await self._repo.apply_lesson_order(remaining)
        await self._repo.session.commit()

    async def reorder_lessons(
        self, module_id: uuid.UUID, ordered_ids: list[uuid.UUID]
    ) -> ReorderResult:
        """Replace the lesson order within a module."""
        module = await self._repo.get_module(module_id)
        if module is None:
            raise NotFoundError("That module could not be found.")

        current = await self._repo.lesson_ids_for_module(module_id)
        self._assert_same_members(current, ordered_ids, noun="lesson")

        await self._repo.apply_lesson_order(ordered_ids)
        await self._repo.session.commit()

        return ReorderResult(
            items=[
                OrderedItem(id=item_id, position=index) for index, item_id in enumerate(ordered_ids)
            ]
        )

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _assert_same_members(
        current: list[uuid.UUID], supplied: list[uuid.UUID], *, noun: str
    ) -> None:
        """Require the supplied ids to be exactly the current membership.

        A partial list would silently drop the omitted items to arbitrary
        positions; an extra id would mean reordering something from another
        parent. Rejecting both is what makes whole-set replacement safe.
        """
        if set(current) != set(supplied):
            missing = len(set(current) - set(supplied))
            unknown = len(set(supplied) - set(current))
            raise ValidationError(
                f"The {noun} list must contain exactly the current {noun}s.",
                details=[
                    {
                        "field": "ordered_ids",
                        "message": (f"{missing} {noun}(s) missing, {unknown} not recognised."),
                    }
                ],
            )

    async def _resolve_course_slug(self, supplied: str | None, title: str) -> str:
        """Pick a course slug, deriving one from the title when not supplied."""
        if supplied is not None:
            existing = await self._repo.get_by_slug_any_status(supplied)
            if existing is not None:
                raise ConflictError("That slug is already used by another course.")
            return supplied

        base = slugify(title) or "course"
        taken = await self._repo.taken_course_slugs(base)
        return unique_slug(title, taken=taken, fallback="course")

    async def _resolve_lesson_slug(
        self, course_id: uuid.UUID, supplied: str | None, title: str
    ) -> str:
        """Pick a lesson slug, unique within its course."""
        base = slugify(supplied or title) or "lesson"
        taken = await self._repo.taken_lesson_slugs(course_id, base)

        if supplied is not None:
            if supplied in taken:
                raise ConflictError("That slug is already used by another lesson in this course.")
            return supplied

        return unique_slug(title, taken=taken, fallback="lesson")

    async def _commit_or_conflict(self, message: str) -> None:
        """Commit, translating a unique-constraint violation into a 409.

        The uniqueness pre-checks above race: two admins can create the same slug
        between the SELECT and the INSERT. The database constraint is the actual
        guarantee, and this turns its violation into a clear client error rather
        than a 500.
        """
        try:
            await self._repo.session.commit()
        except IntegrityError as exc:
            await self._repo.session.rollback()
            logger.info("catalogue_integrity_conflict", error=type(exc).__name__)
            raise ConflictError(message) from exc

    # ── Projections ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_summary(
        course: Course, lesson_count: int, total_duration_seconds: int
    ) -> CourseSummary:
        """Project a course row onto the catalogue list schema."""
        return CourseSummary(
            id=course.id,
            slug=course.slug,
            title=course.title,
            subtitle=course.subtitle,
            specialty=course.specialty,
            difficulty=course.difficulty,
            cover_image_key=course.cover_image_key,
            lesson_count=lesson_count,
            total_duration_seconds=total_duration_seconds,
            published_at=course.published_at,
        )

    @staticmethod
    def _to_module_read(module: Module) -> ModuleRead:
        """Project a module and its loaded lessons."""
        return ModuleRead(
            id=module.id,
            title=module.title,
            summary=module.summary,
            position=module.position,
            lessons=[
                LessonSummary.model_validate(lesson)
                for lesson in sorted(module.lessons, key=lambda item: item.position)
            ],
        )

    @classmethod
    def _to_detail(cls, course: Course, modules: list[ModuleRead] | None = None) -> CourseDetail:
        """Project a course and its outline.

        Counts are derived from the loaded outline rather than re-queried, so
        rendering a course detail page costs no extra round-trip.
        """
        outline = (
            modules
            if modules is not None
            else [
                cls._to_module_read(module)
                for module in sorted(course.modules, key=lambda item: item.position)
            ]
        )
        lessons = [lesson for module in outline for lesson in module.lessons]

        return CourseDetail(
            id=course.id,
            slug=course.slug,
            title=course.title,
            subtitle=course.subtitle,
            description=course.description,
            specialty=course.specialty,
            difficulty=course.difficulty,
            status=course.status,
            cover_image_key=course.cover_image_key,
            lesson_count=len(lessons),
            total_duration_seconds=sum(lesson.duration_seconds or 0 for lesson in lessons),
            published_at=course.published_at,
            modules=outline,
            created_at=course.created_at,
            updated_at=course.updated_at,
        )
