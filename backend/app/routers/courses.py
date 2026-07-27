"""Student-facing catalogue routes.

Every route requires a **verified** user. Unverified accounts can read their own
profile (so they can act on the verification prompt) but not course content —
this is the first feature to actually use `VerifiedUserDep`, which Feature 1 put
in place.

Admin authoring lives in `routers/admin_courses.py`. Keeping the two apart means
a student route can never accidentally inherit an admin-shaped query, and the
`/admin` prefix carries a blanket role guard rather than a per-route one.
"""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import ValidationError as PydanticValidationError

from app.core.dependencies import CourseServiceDep, MediaServiceDep, VerifiedUserDep
from app.core.envelope import create_router
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.common import Page, SuccessResponse
from app.schemas.course import (
    CatalogueFilters,
    CourseDetail,
    CourseSummary,
    LessonDetail,
)
from app.schemas.media import PlaybackTicket

router = create_router(prefix="/courses", tags=["courses"])


def catalogue_filters(
    q: Annotated[str | None, Query(max_length=120, description="Free-text search")] = None,
    specialty: Annotated[str | None, Query(max_length=120)] = None,
    difficulty: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> CatalogueFilters:
    """Validate query parameters through the shared schema.

    Declared as a dependency so the rules live in `schemas/course.py` with
    everything else, and a malformed `difficulty` produces the same enveloped
    422 as a malformed request body.
    """
    try:
        return CatalogueFilters.model_validate(
            {
                "q": q,
                "specialty": specialty,
                "difficulty": difficulty,
                "limit": limit,
                "cursor": cursor,
            }
        )
    except PydanticValidationError as exc:
        # Validating a model by hand bypasses FastAPI's automatic conversion, so
        # without this an unknown `difficulty` would escape as a 500.
        raise ValidationError.from_pydantic(exc) from exc


CatalogueFiltersDep = Annotated[CatalogueFilters, Depends(catalogue_filters)]


@router.get(
    "",
    response_model=SuccessResponse[Page[CourseSummary]],
    summary="Browse the published course catalogue",
)
async def list_courses(
    filters: CatalogueFiltersDep,
    service: CourseServiceDep,
    _user: VerifiedUserDep,
) -> Page[CourseSummary]:
    """Return one cursor-paginated page of published courses, newest first."""
    return await service.list_catalogue(filters)


@router.get(
    "/{slug}",
    response_model=SuccessResponse[CourseDetail],
    summary="Get a published course and its outline",
)
async def get_course(
    slug: str,
    service: CourseServiceDep,
    _user: VerifiedUserDep,
) -> CourseDetail:
    """Return a published course with its modules and published lessons.

    A draft or archived course returns 404 rather than 403, so this endpoint
    cannot be used to probe for unreleased content.
    """
    return await service.get_course(slug)


@router.get(
    "/{slug}/lessons/{lesson_slug}",
    response_model=SuccessResponse[LessonDetail],
    summary="Get a published lesson",
)
async def get_lesson(
    slug: str,
    lesson_slug: str,
    service: CourseServiceDep,
    _user: VerifiedUserDep,
) -> LessonDetail:
    """Return a single published lesson within a published course."""
    return await service.get_lesson(course_slug=slug, lesson_slug=lesson_slug)


@router.get(
    "/{slug}/lessons/{lesson_slug}/playback",
    response_model=SuccessResponse[PlaybackTicket],
    summary="Get a short-lived playback URL for a lesson's video",
)
async def get_lesson_playback(
    slug: str,
    lesson_slug: str,
    courses: CourseServiceDep,
    media: MediaServiceDep,
    _user: VerifiedUserDep,
) -> PlaybackTicket:
    """Issue a signed URL for the lesson's video.

    Authorisation happens here, not in the URL: the returned link carries no
    identity, so anyone holding it can read the object until it expires. That is
    why the TTL is minutes and a fresh ticket is issued per view rather than
    cached by the client.

    Returns `404` if the lesson has no video — the same response as a lesson that
    does not exist, so this cannot be used to enumerate which lessons have
    recordings ready.
    """
    lesson = await courses.get_lesson_for_playback(course_slug=slug, lesson_slug=lesson_slug)
    if lesson.video_asset_id is None:
        raise NotFoundError("No video is available for this lesson.")

    asset = await media.get_ready_asset(lesson.video_asset_id)
    return media.issue_playback_ticket(asset, duration_seconds=lesson.duration_seconds)
