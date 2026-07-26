"""Admin authoring tests.

Covers the publication lifecycle, ordering, and the two schema-level guarantees:
deferrable position constraints (reorder works atomically) and the composite
foreign key (a lesson's course cannot disagree with its module's).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import ContentStatus, Course, Lesson, Module
from app.models.profile import UserRole
from tests.conftest import TokenFactory
from tests.integration.test_auth_router import assert_error, assert_success, auth_header

ADMIN = "/api/v1/admin"


@pytest.fixture
async def admin_token(tokens: TokenFactory, make_user: Any) -> str:
    """A token for an account that is an admin in the database, not just in the claim."""
    user = await make_user(role="admin", with_profile=True, profile_role=UserRole.ADMIN)
    return tokens.create(user_id=user.id, role="admin")


# ── Authorization ────────────────────────────────────────────────────────────


async def test_admin_routes_reject_a_student(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """The router-level guard applies to every route in the module."""
    user = await make_user(role="student", with_profile=True)

    response = await client.get(
        f"{ADMIN}/courses", headers=auth_header(tokens.create(user_id=user.id))
    )

    assert response.status_code == 403
    assert_error(response.json(), "FORBIDDEN")


async def test_admin_routes_reject_a_forged_admin_claim(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """The role is read from the database, never from the token."""
    user = await make_user(role="student", with_profile=True)

    response = await client.post(
        f"{ADMIN}/courses",
        headers=auth_header(tokens.create(user_id=user.id, role="admin")),
        json={"title": "Sneaky Course"},
    )

    assert response.status_code == 403


# ── Course lifecycle ─────────────────────────────────────────────────────────


async def test_create_course_starts_as_a_draft_with_a_derived_slug(
    client: AsyncClient, admin_token: str
) -> None:
    response = await client.post(
        f"{ADMIN}/courses",
        headers=auth_header(admin_token),
        json={"title": "Clinical Cardiology!", "specialty": "Cardiology"},
    )

    assert response.status_code == 201
    data = assert_success(response.json())
    assert data["status"] == "draft"
    assert data["slug"] == "clinical-cardiology"
    assert data["published_at"] is None
    assert data["modules"] == []


async def test_create_course_cannot_be_published_directly(
    client: AsyncClient, admin_token: str
) -> None:
    """`status` is absent from the create schema, so publishing must go through
    the publish endpoint and its checks."""
    response = await client.post(
        f"{ADMIN}/courses",
        headers=auth_header(admin_token),
        json={"title": "Instant", "status": "published"},
    )

    assert response.status_code == 422
    assert_error(response.json(), "VALIDATION_ERROR")


async def test_create_course_records_the_authenticated_author(
    client: AsyncClient, session: AsyncSession, admin_token: str, tokens: TokenFactory
) -> None:
    """Authorship comes from the token, so it cannot be attributed to someone else."""
    response = await client.post(
        f"{ADMIN}/courses", headers=auth_header(admin_token), json={"title": "Authored"}
    )

    course_id = uuid.UUID(assert_success(response.json())["id"])
    course = await session.get(Course, course_id)
    assert course is not None
    assert course.created_by is not None


async def test_create_course_deduplicates_a_derived_slug(
    client: AsyncClient, admin_token: str
) -> None:
    first = await client.post(
        f"{ADMIN}/courses", headers=auth_header(admin_token), json={"title": "Anatomy"}
    )
    second = await client.post(
        f"{ADMIN}/courses", headers=auth_header(admin_token), json={"title": "Anatomy"}
    )

    assert assert_success(first.json())["slug"] == "anatomy"
    assert assert_success(second.json())["slug"] == "anatomy-2"


async def test_create_course_rejects_a_duplicate_explicit_slug(
    client: AsyncClient, admin_token: str
) -> None:
    await client.post(
        f"{ADMIN}/courses",
        headers=auth_header(admin_token),
        json={"title": "First", "slug": "shared-slug"},
    )
    response = await client.post(
        f"{ADMIN}/courses",
        headers=auth_header(admin_token),
        json={"title": "Second", "slug": "shared-slug"},
    )

    assert response.status_code == 409
    assert_error(response.json(), "CONFLICT")


async def test_create_course_rejects_a_malformed_explicit_slug(
    client: AsyncClient, admin_token: str
) -> None:
    """An explicit slug is validated, not silently rewritten — the resulting URL
    should never be a surprise."""
    response = await client.post(
        f"{ADMIN}/courses",
        headers=auth_header(admin_token),
        json={"title": "Anatomy", "slug": "Not A Slug"},
    )

    assert response.status_code == 422
    detail = response.json()["error"]["details"][0]
    assert detail["field"] == "slug"
    # The message suggests the corrected form rather than just rejecting.
    assert "not-a-slug" in detail["message"]


async def test_publish_requires_at_least_one_lesson(client: AsyncClient, admin_token: str) -> None:
    """A published course with an empty outline is a broken landing page."""
    created = await client.post(
        f"{ADMIN}/courses", headers=auth_header(admin_token), json={"title": "Empty"}
    )
    course_id = assert_success(created.json())["id"]

    response = await client.post(
        f"{ADMIN}/courses/{course_id}/publish", headers=auth_header(admin_token)
    )

    assert response.status_code == 422
    assert_error(response.json(), "VALIDATION_ERROR")


async def test_publish_cascades_to_draft_lessons(
    client: AsyncClient, admin_token: str, make_course: Any
) -> None:
    course = await make_course(status=ContentStatus.DRAFT, modules=2, lessons_per_module=2)

    response = await client.post(
        f"{ADMIN}/courses/{course.id}/publish", headers=auth_header(admin_token)
    )

    data = assert_success(response.json())
    assert data["status"] == "published"
    assert data["published_at"] is not None
    assert data["lesson_count"] == 4


async def test_publish_is_idempotent(
    client: AsyncClient, admin_token: str, make_course: Any
) -> None:
    course = await make_course(status=ContentStatus.DRAFT, lessons_per_module=1)

    first = await client.post(
        f"{ADMIN}/courses/{course.id}/publish", headers=auth_header(admin_token)
    )
    second = await client.post(
        f"{ADMIN}/courses/{course.id}/publish", headers=auth_header(admin_token)
    )

    assert first.status_code == 200
    assert second.status_code == 200
    # Republishing must not move the original publication date.
    assert (
        assert_success(first.json())["published_at"]
        == assert_success(second.json())["published_at"]
    )


async def test_published_slug_is_immutable(
    client: AsyncClient, admin_token: str, make_course: Any
) -> None:
    """Renaming a live URL breaks every bookmark and inbound link."""
    course = await make_course(slug="live-course", status=ContentStatus.PUBLISHED)

    response = await client.patch(
        f"{ADMIN}/courses/{course.id}",
        headers=auth_header(admin_token),
        json={"slug": "renamed"},
    )

    assert response.status_code == 409
    assert_error(response.json(), "CONFLICT")


async def test_draft_slug_can_still_be_changed(
    client: AsyncClient, admin_token: str, make_course: Any
) -> None:
    course = await make_course(slug="draft-course", status=ContentStatus.DRAFT)

    response = await client.patch(
        f"{ADMIN}/courses/{course.id}",
        headers=auth_header(admin_token),
        json={"slug": "better-name"},
    )

    assert assert_success(response.json())["slug"] == "better-name"


async def test_archive_removes_a_course_from_the_catalogue(
    client: AsyncClient,
    admin_token: str,
    tokens: TokenFactory,
    make_user: Any,
    make_course: Any,
) -> None:
    course = await make_course(slug="retiring", status=ContentStatus.PUBLISHED)
    student = await make_user(with_profile=True)

    await client.post(f"{ADMIN}/courses/{course.id}/archive", headers=auth_header(admin_token))
    catalogue = await client.get(
        "/api/v1/courses", headers=auth_header(tokens.create(user_id=student.id))
    )

    assert assert_success(catalogue.json())["items"] == []


async def test_admin_listing_includes_drafts(
    client: AsyncClient, admin_token: str, make_course: Any
) -> None:
    await make_course(title="Published one", status=ContentStatus.PUBLISHED)
    await make_course(title="Draft one", status=ContentStatus.DRAFT)

    response = await client.get(f"{ADMIN}/courses", headers=auth_header(admin_token))

    titles = {item["title"] for item in assert_success(response.json())["items"]}
    assert titles == {"Published one", "Draft one"}


async def test_admin_course_detail_includes_draft_lessons(
    client: AsyncClient, admin_token: str, make_course: Any
) -> None:
    """Authors must see what students cannot."""
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=3)

    response = await client.get(f"{ADMIN}/courses/{course.id}", headers=auth_header(admin_token))

    data = assert_success(response.json())
    assert len(data["modules"][0]["lessons"]) == 3


# ── Modules and lessons ──────────────────────────────────────────────────────


async def test_modules_are_appended_in_order(
    client: AsyncClient, admin_token: str, make_course: Any
) -> None:
    course = await make_course(status=ContentStatus.DRAFT, modules=0)

    positions = []
    for index in range(3):
        response = await client.post(
            f"{ADMIN}/courses/{course.id}/modules",
            headers=auth_header(admin_token),
            json={"title": f"Module {index}"},
        )
        positions.append(assert_success(response.json())["position"])

    assert positions == [0, 1, 2]


async def test_lesson_inherits_its_course_from_the_module(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    """`course_id` is derived server-side, so the client cannot express a mismatch."""
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=0)
    module = (await session.scalars(select(Module).where(Module.course_id == course.id))).first()
    assert module is not None

    response = await client.post(
        f"{ADMIN}/modules/{module.id}/lessons",
        headers=auth_header(admin_token),
        json={"title": "Introduction", "duration_seconds": 300},
    )

    data = assert_success(response.json())
    assert data["course_id"] == str(course.id)
    assert data["status"] == "draft"
    assert data["slug"] == "introduction"


async def test_lesson_slugs_are_unique_per_course_not_globally(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    """Two courses may each have an "introduction"; the URL is course-scoped."""
    slugs = []
    for index in range(2):
        course = await make_course(
            slug=f"course-{index}", status=ContentStatus.DRAFT, modules=1, lessons_per_module=0
        )
        module = (
            await session.scalars(select(Module).where(Module.course_id == course.id))
        ).first()
        assert module is not None
        response = await client.post(
            f"{ADMIN}/modules/{module.id}/lessons",
            headers=auth_header(admin_token),
            json={"title": "Introduction"},
        )
        slugs.append(assert_success(response.json())["slug"])

    assert slugs == ["introduction", "introduction"]


async def test_duplicate_lesson_slug_within_a_course_is_deduplicated(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=0)
    module = (await session.scalars(select(Module).where(Module.course_id == course.id))).first()
    assert module is not None

    slugs = []
    for _ in range(2):
        response = await client.post(
            f"{ADMIN}/modules/{module.id}/lessons",
            headers=auth_header(admin_token),
            json={"title": "Overview"},
        )
        slugs.append(assert_success(response.json())["slug"])

    assert slugs == ["overview", "overview-2"]


async def test_deleting_a_lesson_closes_the_position_gap(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    """A gap would make the next append land on an unexpected index."""
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=3)
    lessons = list(
        (
            await session.scalars(
                select(Lesson).where(Lesson.course_id == course.id).order_by(Lesson.position)
            )
        ).all()
    )

    response = await client.delete(
        f"{ADMIN}/lessons/{lessons[1].id}", headers=auth_header(admin_token)
    )
    assert response.status_code == 204

    remaining = list(
        (
            await session.scalars(
                select(Lesson).where(Lesson.course_id == course.id).order_by(Lesson.position)
            )
        ).all()
    )
    assert [lesson.position for lesson in remaining] == [0, 1]


# ── Reordering ───────────────────────────────────────────────────────────────


async def test_reordering_modules_rewrites_every_position(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    """Exercises the deferrable unique constraint: positions collide mid-rewrite
    and are only validated at COMMIT."""
    course = await make_course(status=ContentStatus.DRAFT, modules=3, lessons_per_module=0)
    modules = list(
        (
            await session.scalars(
                select(Module).where(Module.course_id == course.id).order_by(Module.position)
            )
        ).all()
    )
    reversed_ids = [str(module.id) for module in reversed(modules)]

    response = await client.put(
        f"{ADMIN}/courses/{course.id}/module-order",
        headers=auth_header(admin_token),
        json={"ordered_ids": reversed_ids},
    )

    assert response.status_code == 200
    data = assert_success(response.json())
    assert [item["position"] for item in data["items"]] == [0, 1, 2]
    assert [item["id"] for item in data["items"]] == reversed_ids


async def test_reordering_rejects_a_partial_list(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    """A partial list would silently relocate the omitted modules."""
    course = await make_course(status=ContentStatus.DRAFT, modules=3, lessons_per_module=0)
    modules = list(
        (await session.scalars(select(Module).where(Module.course_id == course.id))).all()
    )

    response = await client.put(
        f"{ADMIN}/courses/{course.id}/module-order",
        headers=auth_header(admin_token),
        json={"ordered_ids": [str(modules[0].id)]},
    )

    assert response.status_code == 422
    assert_error(response.json(), "VALIDATION_ERROR")


async def test_reordering_rejects_a_foreign_id(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    """An id from another course must not be draggable into this one."""
    course = await make_course(status=ContentStatus.DRAFT, modules=2, lessons_per_module=0)
    other = await make_course(
        slug="other-course", status=ContentStatus.DRAFT, modules=1, lessons_per_module=0
    )
    modules = list(
        (await session.scalars(select(Module).where(Module.course_id == course.id))).all()
    )
    foreign = (await session.scalars(select(Module).where(Module.course_id == other.id))).first()
    assert foreign is not None

    response = await client.put(
        f"{ADMIN}/courses/{course.id}/module-order",
        headers=auth_header(admin_token),
        json={"ordered_ids": [str(modules[0].id), str(foreign.id)]},
    )

    assert response.status_code == 422


async def test_reordering_rejects_duplicate_ids(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    course = await make_course(status=ContentStatus.DRAFT, modules=2, lessons_per_module=0)
    modules = list(
        (await session.scalars(select(Module).where(Module.course_id == course.id))).all()
    )

    response = await client.put(
        f"{ADMIN}/courses/{course.id}/module-order",
        headers=auth_header(admin_token),
        json={"ordered_ids": [str(modules[0].id), str(modules[0].id)]},
    )

    assert response.status_code == 422


async def test_reordering_lessons_rewrites_positions(
    client: AsyncClient, session: AsyncSession, admin_token: str, make_course: Any
) -> None:
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=4)
    module = (await session.scalars(select(Module).where(Module.course_id == course.id))).first()
    assert module is not None
    lessons = list(
        (
            await session.scalars(
                select(Lesson).where(Lesson.module_id == module.id).order_by(Lesson.position)
            )
        ).all()
    )
    shuffled = [lessons[2], lessons[0], lessons[3], lessons[1]]

    response = await client.put(
        f"{ADMIN}/modules/{module.id}/lesson-order",
        headers=auth_header(admin_token),
        json={"ordered_ids": [str(lesson.id) for lesson in shuffled]},
    )

    assert response.status_code == 200
    assert [item["id"] for item in assert_success(response.json())["items"]] == [
        str(lesson.id) for lesson in shuffled
    ]


# ── Schema-level guarantees ──────────────────────────────────────────────────


async def test_composite_foreign_key_blocks_a_mismatched_course(
    session: AsyncSession, make_course: Any
) -> None:
    """The database itself refuses a lesson whose course differs from its module's.

    This is the guarantee that makes the denormalised `course_id` safe. Asserted
    directly against Postgres, because it protects against a bug in *future*
    application code that the service layer cannot anticipate.
    """
    course_a = await make_course(slug="course-a", modules=1, lessons_per_module=0)
    course_b = await make_course(slug="course-b", modules=1, lessons_per_module=0)
    module_a = (
        await session.scalars(select(Module).where(Module.course_id == course_a.id))
    ).first()
    assert module_a is not None

    session.add(
        Lesson(
            module_id=module_a.id,
            course_id=course_b.id,  # deliberately wrong
            slug="smuggled",
            title="Smuggled",
            position=0,
            status=ContentStatus.DRAFT,
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_published_course_must_have_a_publication_timestamp(
    session: AsyncSession,
) -> None:
    """The check constraint prevents a published course with a null date, which
    would break both the catalogue ordering and its cursor."""
    session.add(
        Course(
            slug="no-timestamp",
            title="No timestamp",
            status=ContentStatus.PUBLISHED,
            published_at=None,
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
