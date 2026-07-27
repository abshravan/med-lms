"""Media upload and playback tests.

The S3 tests run against a **real in-process S3 server** (`moto`), so presigned
URLs are exercised with genuine PUT and GET traffic rather than asserted on as
strings. A URL that boto3 generates but the server rejects — the usual outcome of
a signing or addressing-style mistake — fails here rather than in production.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from moto.server import ThreadedMotoServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import ContentStatus, Lesson
from app.models.media import MediaAsset, MediaKind, MediaStatus
from app.models.profile import UserRole
from app.services.storage import (
    LocalStorageProvider,
    ObjectNotFoundError,
    S3StorageProvider,
    set_storage_provider,
)
from tests.conftest import TokenFactory
from tests.integration.test_auth_router import assert_error, assert_success, auth_header

ADMIN_MEDIA = "/api/v1/admin/media"
BUCKET = "med-lms-test"

_server_lock = threading.Lock()


# ── Storage backends under test ──────────────────────────────────────────────


@pytest.fixture(scope="session")
def moto_server() -> Iterator[str]:
    """A real S3 server on a random port, shared across the session."""
    with _server_lock:
        server = ThreadedMotoServer(port=0, verbose=False)
        server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def s3_provider(moto_server: str) -> Iterator[S3StorageProvider]:
    """An S3 provider pointed at moto, with a freshly created bucket."""
    provider = S3StorageProvider(
        bucket=BUCKET,
        endpoint_url=moto_server,
        access_key_id="test-key",
        secret_access_key="test-secret",  # noqa: S106
        region="us-east-1",
    )
    provider._client.create_bucket(Bucket=BUCKET)  # noqa: SLF001 - test setup
    set_storage_provider(provider)
    yield provider
    set_storage_provider(None)


@pytest.fixture
def local_provider(tmp_path: Path) -> Iterator[LocalStorageProvider]:
    """The development filesystem provider, rooted in a temp directory."""
    provider = LocalStorageProvider(
        root=tmp_path / "media",
        base_url="http://api.test",
        signing_secret="test-signing-secret",  # noqa: S106
    )
    set_storage_provider(provider)
    yield provider
    set_storage_provider(None)


@pytest.fixture
async def admin_token(tokens: TokenFactory, make_user: Any) -> str:
    user = await make_user(role="admin", with_profile=True, profile_role=UserRole.ADMIN)
    return tokens.create(user_id=user.id, role="admin")


async def put_object(url: str, content: bytes, headers: dict[str, str]) -> httpx.Response:
    """PUT directly to storage, exactly as the browser does."""
    async with httpx.AsyncClient(timeout=30) as http:
        return await http.put(url, content=content, headers=headers)


async def get_object(url: str) -> httpx.Response:
    """GET directly from storage, exactly as a video element does."""
    async with httpx.AsyncClient(timeout=30) as http:
        return await http.get(url)


VIDEO_REQUEST = {
    "kind": "lesson_video",
    "filename": "lecture.mp4",
    "content_type": "video/mp4",
    "size_bytes": 1024,
}


# ── Provider-level behaviour, against a real S3 server ───────────────────────


class TestS3Provider:
    def test_presigned_put_then_get_round_trips(self, s3_provider: S3StorageProvider) -> None:
        """The generated URLs must work against an actual S3 implementation."""
        upload = s3_provider.create_presigned_upload(
            storage_key="lesson_video/2026/07/abc.mp4",
            content_type="video/mp4",
            expires_in_seconds=300,
        )
        put = httpx.put(upload.url, content=b"fake-video-bytes", headers=upload.headers)
        assert put.status_code in (200, 204)

        download = s3_provider.create_presigned_download(
            storage_key=upload.storage_key, expires_in_seconds=300
        )
        assert httpx.get(download).content == b"fake-video-bytes"

    def test_upload_url_binds_the_content_type(self, s3_provider: S3StorageProvider) -> None:
        """The content type must be part of the signature.

        Without that binding a client could obtain an upload URL for a video and
        store an HTML document, which the CDN would later serve back — executing
        script from the platform's own origin.

        > This asserts the URL's *structure* rather than a rejected upload,
        > because moto does not verify presigned signatures: it accepts a
        > mismatched `Content-Type` that real S3 and R2 reject with 403. The
        > binding is what we control, so the binding is what is asserted here.
        > End-to-end rejection needs a MinIO or real-R2 integration environment.
        """
        upload = s3_provider.create_presigned_upload(
            storage_key="lesson_video/2026/07/bound.mp4",
            content_type="video/mp4",
            expires_in_seconds=300,
        )

        assert "X-Amz-SignedHeaders=content-type%3Bhost" in upload.url
        # And the client is told to send exactly that type.
        assert upload.headers["Content-Type"] == "video/mp4"
        assert "X-Amz-Expires=300" in upload.url

    def test_head_reports_the_real_size(self, s3_provider: S3StorageProvider) -> None:
        upload = s3_provider.create_presigned_upload(
            storage_key="lesson_video/2026/07/sized.mp4",
            content_type="video/mp4",
            expires_in_seconds=300,
        )
        httpx.put(upload.url, content=b"x" * 4096, headers=upload.headers)

        stored = s3_provider.head(storage_key=upload.storage_key)
        assert stored.size_bytes == 4096

    def test_head_raises_for_a_missing_object(self, s3_provider: S3StorageProvider) -> None:
        with pytest.raises(ObjectNotFoundError):
            s3_provider.head(storage_key="lesson_video/2026/07/never-uploaded.mp4")

    def test_delete_is_idempotent(self, s3_provider: S3StorageProvider) -> None:
        s3_provider.delete(storage_key="lesson_video/2026/07/absent.mp4")


class TestLocalProvider:
    def test_signature_is_required(self, local_provider: LocalStorageProvider) -> None:
        assert not local_provider.verify(
            storage_key="k", method="PUT", expires_at=9_999_999_999, signature="wrong"
        )

    def test_an_expired_signature_is_rejected(self, local_provider: LocalStorageProvider) -> None:
        upload = local_provider.create_presigned_upload(
            storage_key="k", content_type="video/mp4", expires_in_seconds=60
        )
        # Re-sign with a past expiry: a valid signature over a stale timestamp.
        expired = local_provider._sign(  # noqa: SLF001 - exercising expiry directly
            storage_key="k", method="PUT", expires_at=1
        )
        assert upload.url  # sanity
        assert not local_provider.verify(
            storage_key="k", method="PUT", expires_at=1, signature=expired
        )

    def test_an_upload_signature_cannot_be_replayed_as_a_download(
        self, local_provider: LocalStorageProvider
    ) -> None:
        """The HTTP method is part of the signature."""
        signature = local_provider._sign(  # noqa: SLF001
            storage_key="k", method="PUT", expires_at=9_999_999_999
        )
        assert not local_provider.verify(
            storage_key="k", method="GET", expires_at=9_999_999_999, signature=signature
        )

    def test_path_traversal_is_blocked(self, local_provider: LocalStorageProvider) -> None:
        """Keys are server-generated, but the write path defends itself anyway."""
        from app.services.storage import StorageError

        with pytest.raises(StorageError):
            local_provider.write(storage_key="../../etc/passwd", data=b"x")


# ── Upload lifecycle through the API ─────────────────────────────────────────


async def test_upload_requires_admin(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, s3_provider: Any
) -> None:
    user = await make_user(role="student", with_profile=True)

    response = await client.post(
        f"{ADMIN_MEDIA}/uploads",
        headers=auth_header(tokens.create(user_id=user.id)),
        json=VIDEO_REQUEST,
    )

    assert response.status_code == 403
    assert_error(response.json(), "FORBIDDEN")


async def test_upload_ticket_is_issued_with_a_server_generated_key(
    client: AsyncClient, admin_token: str, s3_provider: Any
) -> None:
    response = await client.post(
        f"{ADMIN_MEDIA}/uploads", headers=auth_header(admin_token), json=VIDEO_REQUEST
    )

    assert response.status_code == 201
    ticket = assert_success(response.json())
    assert ticket["method"] == "PUT"
    assert ticket["headers"]["Content-Type"] == "video/mp4"
    # The key is derived from the kind and content type, never the filename.
    assert ticket["storage_key"].startswith("lesson_video/")
    assert ticket["storage_key"].endswith(".mp4")
    assert "lecture" not in ticket["storage_key"]


async def test_upload_rejects_a_disallowed_content_type(
    client: AsyncClient, admin_token: str, s3_provider: Any
) -> None:
    response = await client.post(
        f"{ADMIN_MEDIA}/uploads",
        headers=auth_header(admin_token),
        json={**VIDEO_REQUEST, "content_type": "text/html"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "content_type"


async def test_upload_rejects_a_mismatched_kind_and_type(
    client: AsyncClient, admin_token: str, s3_provider: Any
) -> None:
    """A PDF cannot be uploaded as a lesson video."""
    response = await client.post(
        f"{ADMIN_MEDIA}/uploads",
        headers=auth_header(admin_token),
        json={**VIDEO_REQUEST, "content_type": "application/pdf"},
    )

    assert response.status_code == 422


async def test_upload_rejects_an_oversized_declaration(
    client: AsyncClient, admin_token: str, s3_provider: Any
) -> None:
    response = await client.post(
        f"{ADMIN_MEDIA}/uploads",
        headers=auth_header(admin_token),
        json={**VIDEO_REQUEST, "size_bytes": 5 * 1024**3},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "size_bytes"


async def test_a_cover_image_uses_the_image_size_ceiling(
    client: AsyncClient, admin_token: str, s3_provider: Any
) -> None:
    """Limits are per-kind, so a cover cannot smuggle in a 2 GB upload."""
    response = await client.post(
        f"{ADMIN_MEDIA}/uploads",
        headers=auth_header(admin_token),
        json={
            "kind": "course_cover",
            "filename": "cover.png",
            "content_type": "image/png",
            "size_bytes": 50 * 1024**2,
        },
    )

    assert response.status_code == 422


async def test_full_upload_and_confirm_flow(
    client: AsyncClient, session: AsyncSession, admin_token: str, s3_provider: Any
) -> None:
    """Request a ticket, upload directly to storage, then confirm."""
    ticket = assert_success(
        (
            await client.post(
                f"{ADMIN_MEDIA}/uploads",
                headers=auth_header(admin_token),
                json=VIDEO_REQUEST,
            )
        ).json()
    )

    payload = b"x" * 2048
    put = await put_object(ticket["upload_url"], payload, ticket["headers"])
    assert put.status_code in (200, 204)

    confirm = await client.post(
        f"{ADMIN_MEDIA}/uploads/{ticket['asset_id']}/confirm",
        headers=auth_header(admin_token),
        json={},
    )

    assert confirm.status_code == 200
    asset = assert_success(confirm.json())
    assert asset["status"] == "ready"
    # The size comes from storage, not from the client's declaration of 1024.
    assert asset["size_bytes"] == 2048
    assert asset["confirmed_at"] is not None


async def test_confirming_without_uploading_is_rejected(
    client: AsyncClient, session: AsyncSession, admin_token: str, s3_provider: Any
) -> None:
    """The API verifies the object exists rather than trusting the client.

    This is the whole reason confirmation is a server-side HEAD: otherwise a
    client could mark an asset ready and attach it to a lesson whose video 404s
    for every student.
    """
    ticket = assert_success(
        (
            await client.post(
                f"{ADMIN_MEDIA}/uploads",
                headers=auth_header(admin_token),
                json=VIDEO_REQUEST,
            )
        ).json()
    )

    response = await client.post(
        f"{ADMIN_MEDIA}/uploads/{ticket['asset_id']}/confirm",
        headers=auth_header(admin_token),
        json={},
    )

    assert response.status_code == 409
    assert_error(response.json(), "CONFLICT")

    stored = await session.get(MediaAsset, uuid.UUID(ticket["asset_id"]))
    assert stored is not None
    assert stored.status is MediaStatus.FAILED


async def test_oversized_upload_is_deleted_on_confirmation(
    client: AsyncClient, admin_token: str, s3_provider: S3StorageProvider
) -> None:
    """A presigned PUT cannot cap size, so confirmation is the compensating control."""
    ticket = assert_success(
        (
            await client.post(
                f"{ADMIN_MEDIA}/uploads",
                headers=auth_header(admin_token),
                json={
                    "kind": "course_cover",
                    "filename": "huge.png",
                    "content_type": "image/png",
                    "size_bytes": 1024,
                },
            )
        ).json()
    )

    # Upload far more than declared — nothing stops this at the storage layer.
    await put_object(ticket["upload_url"], b"x" * (11 * 1024**2), ticket["headers"])

    response = await client.post(
        f"{ADMIN_MEDIA}/uploads/{ticket['asset_id']}/confirm",
        headers=auth_header(admin_token),
        json={},
    )

    assert response.status_code == 422
    # The object must not be left behind: it is billed for and still reachable
    # by anyone holding the upload URL.
    with pytest.raises(ObjectNotFoundError):
        s3_provider.head(storage_key=ticket["storage_key"])


async def test_confirmation_is_idempotent(
    client: AsyncClient, admin_token: str, s3_provider: Any
) -> None:
    ticket = assert_success(
        (
            await client.post(
                f"{ADMIN_MEDIA}/uploads",
                headers=auth_header(admin_token),
                json=VIDEO_REQUEST,
            )
        ).json()
    )
    await put_object(ticket["upload_url"], b"data", ticket["headers"])

    first = await client.post(
        f"{ADMIN_MEDIA}/uploads/{ticket['asset_id']}/confirm",
        headers=auth_header(admin_token),
        json={},
    )
    second = await client.post(
        f"{ADMIN_MEDIA}/uploads/{ticket['asset_id']}/confirm",
        headers=auth_header(admin_token),
        json={},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        assert_success(first.json())["confirmed_at"]
        == assert_success(second.json())["confirmed_at"]
    )


# ── Attachment and playback ──────────────────────────────────────────────────


async def _ready_asset(
    client: AsyncClient, admin_token: str, request: dict[str, Any]
) -> dict[str, Any]:
    """Run a full upload + confirm cycle and return the ticket."""
    ticket = assert_success(
        (
            await client.post(
                f"{ADMIN_MEDIA}/uploads", headers=auth_header(admin_token), json=request
            )
        ).json()
    )
    await put_object(ticket["upload_url"], b"payload", ticket["headers"])
    await client.post(
        f"{ADMIN_MEDIA}/uploads/{ticket['asset_id']}/confirm",
        headers=auth_header(admin_token),
        json={},
    )
    return ticket


async def test_attaching_a_video_to_a_lesson(
    client: AsyncClient,
    session: AsyncSession,
    admin_token: str,
    make_course: Any,
    s3_provider: Any,
) -> None:
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=1)
    lesson = (await session.scalars(select(Lesson).where(Lesson.course_id == course.id))).first()
    assert lesson is not None
    ticket = await _ready_asset(client, admin_token, VIDEO_REQUEST)

    response = await client.put(
        f"/api/v1/admin/lessons/{lesson.id}/video",
        headers=auth_header(admin_token),
        json={"asset_id": ticket["asset_id"]},
    )

    assert response.status_code == 200
    await session.refresh(lesson)
    assert str(lesson.video_asset_id) == ticket["asset_id"]


async def test_attaching_a_cover_image_as_a_video_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    admin_token: str,
    make_course: Any,
    s3_provider: Any,
) -> None:
    """Kind is checked server-side; a cover attached as a video renders broken."""
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=1)
    lesson = (await session.scalars(select(Lesson).where(Lesson.course_id == course.id))).first()
    assert lesson is not None
    ticket = await _ready_asset(
        client,
        admin_token,
        {
            "kind": "course_cover",
            "filename": "cover.png",
            "content_type": "image/png",
            "size_bytes": 512,
        },
    )

    response = await client.put(
        f"/api/v1/admin/lessons/{lesson.id}/video",
        headers=auth_header(admin_token),
        json={"asset_id": ticket["asset_id"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "asset_id"


async def test_attaching_an_unconfirmed_asset_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    admin_token: str,
    make_course: Any,
    s3_provider: Any,
) -> None:
    """Attaching a still-uploading file would publish a lesson with a dead video."""
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=1)
    lesson = (await session.scalars(select(Lesson).where(Lesson.course_id == course.id))).first()
    assert lesson is not None
    ticket = assert_success(
        (
            await client.post(
                f"{ADMIN_MEDIA}/uploads",
                headers=auth_header(admin_token),
                json=VIDEO_REQUEST,
            )
        ).json()
    )

    response = await client.put(
        f"/api/v1/admin/lessons/{lesson.id}/video",
        headers=auth_header(admin_token),
        json={"asset_id": ticket["asset_id"]},
    )

    assert response.status_code == 409


async def test_playback_returns_a_working_signed_url(
    client: AsyncClient,
    session: AsyncSession,
    admin_token: str,
    tokens: TokenFactory,
    make_user: Any,
    make_course: Any,
    s3_provider: Any,
) -> None:
    course = await make_course(slug="cardio", modules=1, lessons_per_module=1)
    lesson = (await session.scalars(select(Lesson).where(Lesson.course_id == course.id))).first()
    assert lesson is not None
    ticket = await _ready_asset(client, admin_token, VIDEO_REQUEST)
    await client.put(
        f"/api/v1/admin/lessons/{lesson.id}/video",
        headers=auth_header(admin_token),
        json={"asset_id": ticket["asset_id"]},
    )

    student = await make_user(with_profile=True)
    response = await client.get(
        f"/api/v1/courses/cardio/lessons/{lesson.slug}/playback",
        headers=auth_header(tokens.create(user_id=student.id)),
    )

    assert response.status_code == 200
    playback = assert_success(response.json())
    assert playback["content_type"] == "video/mp4"
    assert 0 < playback["expires_in_seconds"] <= 3600
    # The URL must actually resolve, not merely look plausible.
    assert (await get_object(playback["url"])).status_code == 200


async def test_playback_requires_a_verified_email(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any, s3_provider: Any
) -> None:
    course = await make_course(slug="gated", modules=1, lessons_per_module=1)
    user = await make_user(email_verified=False, with_profile=True)

    response = await client.get(
        f"/api/v1/courses/{course.slug}/lessons/{course.slug}-m0-l0/playback",
        headers=auth_header(tokens.create(user_id=user.id, email_verified=False)),
    )

    assert response.status_code == 403
    assert_error(response.json(), "EMAIL_NOT_VERIFIED")


async def test_playback_for_a_lesson_without_a_video_is_not_found(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, make_course: Any, s3_provider: Any
) -> None:
    """404 rather than a distinct code, so this cannot enumerate which lessons
    have recordings ready."""
    await make_course(slug="silent", modules=1, lessons_per_module=1)
    user = await make_user(with_profile=True)

    response = await client.get(
        "/api/v1/courses/silent/lessons/silent-m0-l0/playback",
        headers=auth_header(tokens.create(user_id=user.id)),
    )

    assert response.status_code == 404


async def test_playback_is_unavailable_for_a_draft_course(
    client: AsyncClient,
    session: AsyncSession,
    admin_token: str,
    tokens: TokenFactory,
    make_user: Any,
    make_course: Any,
    s3_provider: Any,
) -> None:
    """The catalogue's visibility rules still apply to media."""
    course = await make_course(
        slug="unreleased", status=ContentStatus.DRAFT, modules=1, lessons_per_module=1
    )
    lesson = (await session.scalars(select(Lesson).where(Lesson.course_id == course.id))).first()
    assert lesson is not None
    ticket = await _ready_asset(client, admin_token, VIDEO_REQUEST)
    await client.put(
        f"/api/v1/admin/lessons/{lesson.id}/video",
        headers=auth_header(admin_token),
        json={"asset_id": ticket["asset_id"]},
    )

    student = await make_user(with_profile=True)
    response = await client.get(
        f"/api/v1/courses/unreleased/lessons/{lesson.slug}/playback",
        headers=auth_header(tokens.create(user_id=student.id)),
    )

    assert response.status_code == 404


async def test_deleting_an_asset_removes_the_object_and_clears_the_lesson(
    client: AsyncClient,
    session: AsyncSession,
    admin_token: str,
    make_course: Any,
    s3_provider: S3StorageProvider,
) -> None:
    """`ON DELETE SET NULL`: removing a video must not remove the lesson."""
    course = await make_course(status=ContentStatus.DRAFT, modules=1, lessons_per_module=1)
    lesson = (await session.scalars(select(Lesson).where(Lesson.course_id == course.id))).first()
    assert lesson is not None
    ticket = await _ready_asset(client, admin_token, VIDEO_REQUEST)
    await client.put(
        f"/api/v1/admin/lessons/{lesson.id}/video",
        headers=auth_header(admin_token),
        json={"asset_id": ticket["asset_id"]},
    )

    response = await client.delete(
        f"{ADMIN_MEDIA}/assets/{ticket['asset_id']}", headers=auth_header(admin_token)
    )

    assert response.status_code == 204
    with pytest.raises(ObjectNotFoundError):
        s3_provider.head(storage_key=ticket["storage_key"])

    await session.refresh(lesson)
    assert lesson.video_asset_id is None


# ── Storage-key generation ───────────────────────────────────────────────────


class TestStorageKeys:
    def test_keys_are_unique_per_upload(self) -> None:
        from app.services.media_service import MediaService

        keys = {
            MediaService.build_storage_key(kind=MediaKind.LESSON_VIDEO, content_type="video/mp4")
            for _ in range(100)
        }
        assert len(keys) == 100

    def test_extension_comes_from_the_content_type(self) -> None:
        """Not from the filename — `lecture.mp4.html` must not become HTML."""
        from app.services.media_service import MediaService

        key = MediaService.build_storage_key(
            kind=MediaKind.LESSON_ATTACHMENT, content_type="application/pdf"
        )
        assert key.endswith(".pdf")
        assert key.startswith("lesson_attachment/")
