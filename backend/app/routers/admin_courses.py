"""Admin authoring routes for the course catalogue.

The role guard is declared **once, on the router**, rather than repeated on each
route. Every route added to this module inherits it, so a new endpoint cannot be
shipped unprotected by forgetting a decorator — the failure mode of per-route
guards.

`require_role` re-reads the caller's role from the database rather than trusting
the token claim, so a demoted admin loses access immediately (see
docs/architecture.md §3.4).
"""

import uuid
from typing import Annotated

from fastapi import Depends, Query, Response, status

from app.core.dependencies import CourseServiceDep, CurrentUserDep, require_role
from app.core.envelope import create_router
from app.models.course import ContentStatus
from app.models.profile import UserRole
from app.schemas.common import Page, SuccessResponse
from app.schemas.course import (
    CourseCreate,
    CourseDetail,
    CourseSummary,
    CourseUpdate,
    LessonCreate,
    LessonDetail,
    LessonUpdate,
    ModuleCreate,
    ModuleRead,
    ModuleUpdate,
    ReorderRequest,
    ReorderResult,
)

router = create_router(
    prefix="/admin",
    tags=["admin: courses"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


# ── Courses ──────────────────────────────────────────────────────────────────


@router.get(
    "/courses",
    response_model=SuccessResponse[Page[CourseSummary]],
    summary="List all courses, including drafts",
)
async def list_courses(
    service: CourseServiceDep,
    status_filter: Annotated[
        ContentStatus | None, Query(alias="status", description="Filter by status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Page[CourseSummary]:
    """Return one page of courses in any state, newest created first."""
    return await service.list_all_courses(limit=limit, cursor=cursor, status=status_filter)


@router.post(
    "/courses",
    response_model=SuccessResponse[CourseDetail],
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft course",
)
async def create_course(
    payload: CourseCreate,
    service: CourseServiceDep,
    user: CurrentUserDep,
) -> CourseDetail:
    """Create a course. It always starts as a draft.

    Authorship is taken from the authenticated caller, never from the body, so
    one admin cannot attribute a course to another.
    """
    return await service.create_course(payload, author_id=user.user_id)


@router.get(
    "/courses/{course_id}",
    response_model=SuccessResponse[CourseDetail],
    summary="Get a course with its full outline",
)
async def get_course(course_id: uuid.UUID, service: CourseServiceDep) -> CourseDetail:
    """Return a course including draft modules and lessons."""
    return await service.get_course_for_admin(course_id)


@router.patch(
    "/courses/{course_id}",
    response_model=SuccessResponse[CourseDetail],
    summary="Update a course",
)
async def update_course(
    course_id: uuid.UUID, payload: CourseUpdate, service: CourseServiceDep
) -> CourseDetail:
    """Partially update a course. A published course's slug is immutable."""
    return await service.update_course(course_id, payload)


@router.post(
    "/courses/{course_id}/publish",
    response_model=SuccessResponse[CourseDetail],
    summary="Publish a course",
)
async def publish_course(course_id: uuid.UUID, service: CourseServiceDep) -> CourseDetail:
    """Publish a course and every draft lesson it contains.

    Idempotent: publishing an already-published course is a no-op that returns
    the current state rather than an error.
    """
    return await service.publish_course(course_id)


@router.post(
    "/courses/{course_id}/archive",
    response_model=SuccessResponse[CourseDetail],
    summary="Archive a course",
)
async def archive_course(course_id: uuid.UUID, service: CourseServiceDep) -> CourseDetail:
    """Remove a course from the catalogue without destroying it.

    Archiving rather than deleting, because progress records, bookmarks, and quiz
    attempts will reference this content.
    """
    return await service.archive_course(course_id)


# ── Modules ──────────────────────────────────────────────────────────────────


@router.post(
    "/courses/{course_id}/modules",
    response_model=SuccessResponse[ModuleRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a module to a course",
)
async def create_module(
    course_id: uuid.UUID, payload: ModuleCreate, service: CourseServiceDep
) -> ModuleRead:
    """Append a module. Its position is assigned by the server."""
    return await service.create_module(course_id, payload)


@router.patch(
    "/modules/{module_id}",
    response_model=SuccessResponse[ModuleRead],
    summary="Update a module",
)
async def update_module(
    module_id: uuid.UUID, payload: ModuleUpdate, service: CourseServiceDep
) -> ModuleRead:
    """Partially update a module."""
    return await service.update_module(module_id, payload)


@router.delete(
    "/modules/{module_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a module and its lessons",
)
async def delete_module(module_id: uuid.UUID, service: CourseServiceDep) -> Response:
    """Delete a module. Remaining modules are renumbered to stay contiguous.

    Returns 204 with no body, so it is deliberately outside the response
    envelope — there is nothing to wrap.
    """
    await service.delete_module(module_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/courses/{course_id}/module-order",
    response_model=SuccessResponse[ReorderResult],
    summary="Reorder a course's modules",
)
async def reorder_modules(
    course_id: uuid.UUID, payload: ReorderRequest, service: CourseServiceDep
) -> ReorderResult:
    """Replace the module order.

    The body must list **every** module in the course, in the desired order.
    Whole-set replacement is idempotent and cannot produce gaps or duplicates.
    """
    return await service.reorder_modules(course_id, payload.ordered_ids)


# ── Lessons ──────────────────────────────────────────────────────────────────


@router.post(
    "/modules/{module_id}/lessons",
    response_model=SuccessResponse[LessonDetail],
    status_code=status.HTTP_201_CREATED,
    summary="Add a lesson to a module",
)
async def create_lesson(
    module_id: uuid.UUID, payload: LessonCreate, service: CourseServiceDep
) -> LessonDetail:
    """Append a lesson. It starts as a draft."""
    return await service.create_lesson(module_id, payload)


@router.patch(
    "/lessons/{lesson_id}",
    response_model=SuccessResponse[LessonDetail],
    summary="Update a lesson",
)
async def update_lesson(
    lesson_id: uuid.UUID, payload: LessonUpdate, service: CourseServiceDep
) -> LessonDetail:
    """Partially update a lesson. A published lesson's slug is immutable."""
    return await service.update_lesson(lesson_id, payload)


@router.post(
    "/lessons/{lesson_id}/publish",
    response_model=SuccessResponse[LessonDetail],
    summary="Publish a lesson",
)
async def publish_lesson(lesson_id: uuid.UUID, service: CourseServiceDep) -> LessonDetail:
    """Make a lesson visible, once its course is published."""
    return await service.set_lesson_status(lesson_id, publish=True)


@router.post(
    "/lessons/{lesson_id}/unpublish",
    response_model=SuccessResponse[LessonDetail],
    summary="Unpublish a lesson",
)
async def unpublish_lesson(lesson_id: uuid.UUID, service: CourseServiceDep) -> LessonDetail:
    """Hide a lesson from students without deleting it."""
    return await service.set_lesson_status(lesson_id, publish=False)


@router.delete(
    "/lessons/{lesson_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a lesson",
)
async def delete_lesson(lesson_id: uuid.UUID, service: CourseServiceDep) -> Response:
    """Delete a lesson. Siblings are renumbered to stay contiguous."""
    await service.delete_lesson(lesson_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/modules/{module_id}/lesson-order",
    response_model=SuccessResponse[ReorderResult],
    summary="Reorder a module's lessons",
)
async def reorder_lessons(
    module_id: uuid.UUID, payload: ReorderRequest, service: CourseServiceDep
) -> ReorderResult:
    """Replace the lesson order within a module."""
    return await service.reorder_lessons(module_id, payload.ordered_ids)
