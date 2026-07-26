"""Student-facing catalogue tests.

The recurring theme: unpublished content must be invisible, and invisible in a
way that cannot be probed. Every "not found" here is a deliberate choice over
"forbidden".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import ContentStatus, Difficulty
from tests.conftest import TokenFactory
from tests.integration.test_auth_router import assert_error, assert_success, auth_header

CATALOGUE = "/api/v1/courses"


async def test_catalogue_lists_published_courses(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    await make_course(title="Cardiology Basics", modules=2, lessons_per_module=3)

    response = await client.get(CATALOGUE, headers=auth_header(tokens.create(user_id=user.id)))

    assert response.status_code == 200
    data = assert_success(response.json())
    assert len(data["items"]) == 1

    course = data["items"][0]
    assert course["title"] == "Cardiology Basics"
    # Aggregated across modules, counting published lessons only.
    assert course["lesson_count"] == 6
    assert course["total_duration_seconds"] == 6 * 600
    # The list view deliberately omits the outline.
    assert "modules" not in course


async def test_catalogue_hides_draft_and_archived_courses(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    await make_course(title="Published", status=ContentStatus.PUBLISHED)
    await make_course(title="Draft", status=ContentStatus.DRAFT)
    await make_course(title="Archived", status=ContentStatus.ARCHIVED)

    response = await client.get(CATALOGUE, headers=auth_header(tokens.create(user_id=user.id)))

    titles = [item["title"] for item in assert_success(response.json())["items"]]
    assert titles == ["Published"]


async def test_catalogue_requires_a_verified_email(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    """Content is gated on verification; the profile endpoint is not."""
    user = await make_user(email_verified=False, with_profile=True)
    await make_course()

    response = await client.get(
        CATALOGUE,
        headers=auth_header(tokens.create(user_id=user.id, email_verified=False)),
    )

    assert response.status_code == 403
    assert_error(response.json(), "EMAIL_NOT_VERIFIED")


async def test_catalogue_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(CATALOGUE)

    assert response.status_code == 401
    assert_error(response.json(), "UNAUTHENTICATED")


# ── Filtering ────────────────────────────────────────────────────────────────


async def test_catalogue_filters_by_specialty(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    await make_course(title="Heart", specialty="Cardiology")
    await make_course(title="Brain", specialty="Neurology")

    response = await client.get(
        CATALOGUE,
        params={"specialty": "Neurology"},
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    titles = [item["title"] for item in assert_success(response.json())["items"]]
    assert titles == ["Brain"]


async def test_catalogue_filters_by_difficulty(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    await make_course(title="Intro", difficulty=Difficulty.FOUNDATION)
    await make_course(title="Deep", difficulty=Difficulty.ADVANCED)

    response = await client.get(
        CATALOGUE,
        params={"difficulty": "advanced"},
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    titles = [item["title"] for item in assert_success(response.json())["items"]]
    assert titles == ["Deep"]


async def test_catalogue_rejects_an_unknown_difficulty(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(with_profile=True)

    response = await client.get(
        CATALOGUE,
        params={"difficulty": "impossible"},
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    assert response.status_code == 422
    assert_error(response.json(), "VALIDATION_ERROR")


async def test_catalogue_search_matches_title_case_insensitively(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    await make_course(title="Advanced Cardiology", specialty="Cardiology")
    # Specialty set explicitly: search also matches specialty, and the factory
    # would otherwise default this course to "Cardiology" too.
    await make_course(title="Basic Neurology", specialty="Neurology")

    response = await client.get(
        CATALOGUE,
        params={"q": "cardio"},
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    titles = [item["title"] for item in assert_success(response.json())["items"]]
    assert titles == ["Advanced Cardiology"]


# ── Pagination ───────────────────────────────────────────────────────────────


async def test_catalogue_paginates_without_repeating_or_dropping(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    """The core keyset guarantee, over rows sharing nothing but ordering."""
    user = await make_user(with_profile=True)
    base = datetime.now(UTC)
    for index in range(5):
        await make_course(
            title=f"Course {index}",
            published_at=base - timedelta(minutes=index),
            modules=1,
            lessons_per_module=1,
        )
    token = tokens.create(user_id=user.id)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, Any] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get(CATALOGUE, params=params, headers=auth_header(token))
        page = assert_success(response.json())
        seen.extend(item["title"] for item in page["items"])
        cursor = page["pagination"]["next_cursor"]
        if cursor is None:
            break

    assert seen == [f"Course {index}" for index in range(5)]
    assert len(seen) == len(set(seen))


async def test_catalogue_reports_no_cursor_on_the_last_page(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    await make_course()

    response = await client.get(
        CATALOGUE,
        params={"limit": 10},
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    pagination = assert_success(response.json())["pagination"]
    assert pagination["has_more"] is False
    assert pagination["next_cursor"] is None


async def test_catalogue_rejects_a_malformed_cursor(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(with_profile=True)

    response = await client.get(
        CATALOGUE,
        params={"cursor": "not-a-real-cursor"},
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    assert response.status_code == 422
    assert_error(response.json(), "VALIDATION_ERROR")


async def test_catalogue_caps_an_oversized_limit(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """An unbounded page size would be a cheap denial-of-service."""
    user = await make_user(with_profile=True)

    response = await client.get(
        CATALOGUE,
        params={"limit": 5000},
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    assert response.status_code == 422


# ── Course detail ────────────────────────────────────────────────────────────


async def test_course_detail_returns_the_ordered_outline(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    course = await make_course(slug="cardiology", modules=3, lessons_per_module=2)

    response = await client.get(
        f"{CATALOGUE}/{course.slug}", headers=auth_header(tokens.create(user_id=user.id))
    )

    data = assert_success(response.json())
    assert [module["position"] for module in data["modules"]] == [0, 1, 2]
    assert all(
        [lesson["position"] for lesson in module["lessons"]] == [0, 1] for module in data["modules"]
    )
    assert data["lesson_count"] == 6


async def test_course_detail_omits_unpublished_lessons(
    client: AsyncClient,
    session: AsyncSession,
    tokens: TokenFactory,
    make_user: Any,
    make_course: Any,
) -> None:
    """A draft lesson inside a published course must not reach the client."""
    user = await make_user(with_profile=True)
    course = await make_course(slug="mixed", modules=1, lessons_per_module=3)

    # Hide one lesson after the fact, as an author would.
    outline = await session.get(type(course), course.id)
    assert outline is not None
    from sqlalchemy import update

    from app.models.course import Lesson

    await session.execute(
        update(Lesson)
        .where(Lesson.course_id == course.id, Lesson.position == 1)
        .values(status=ContentStatus.DRAFT, published_at=None)
    )
    await session.flush()

    response = await client.get(
        f"{CATALOGUE}/mixed", headers=auth_header(tokens.create(user_id=user.id))
    )

    data = assert_success(response.json())
    lessons = data["modules"][0]["lessons"]
    assert len(lessons) == 2
    assert data["lesson_count"] == 2


async def test_course_detail_reports_a_draft_as_not_found(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    """404 rather than 403, so the endpoint cannot confirm unreleased content."""
    user = await make_user(with_profile=True)
    course = await make_course(slug="secret", status=ContentStatus.DRAFT)

    response = await client.get(
        f"{CATALOGUE}/{course.slug}", headers=auth_header(tokens.create(user_id=user.id))
    )

    assert response.status_code == 404
    assert_error(response.json(), "NOT_FOUND")


async def test_course_detail_reports_an_archived_course_as_not_found(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    course = await make_course(slug="retired", status=ContentStatus.ARCHIVED)

    response = await client.get(
        f"{CATALOGUE}/{course.slug}", headers=auth_header(tokens.create(user_id=user.id))
    )

    assert response.status_code == 404


# ── Lesson detail ────────────────────────────────────────────────────────────


async def test_lesson_detail_returns_a_published_lesson(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    user = await make_user(with_profile=True)
    course = await make_course(slug="anatomy", modules=1, lessons_per_module=1)

    response = await client.get(
        f"{CATALOGUE}/anatomy/lessons/anatomy-m0-l0",
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    data = assert_success(response.json())
    assert data["slug"] == "anatomy-m0-l0"
    assert data["course_id"] == str(course.id)


async def test_lesson_detail_hides_a_lesson_in_a_draft_course(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any
) -> None:
    """Guards compose: a published lesson in a draft course stays invisible."""
    user = await make_user(with_profile=True)
    await make_course(
        slug="unreleased",
        status=ContentStatus.DRAFT,
        lesson_status=ContentStatus.PUBLISHED,
        modules=1,
        lessons_per_module=1,
    )

    response = await client.get(
        f"{CATALOGUE}/unreleased/lessons/unreleased-m0-l0",
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    assert response.status_code == 404
