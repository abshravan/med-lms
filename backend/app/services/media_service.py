"""Media upload and playback business logic.

The load-bearing rule here: **the API never takes the client's word that an
upload happened.** With direct-to-storage uploads the API sees no bytes, so
confirmation HEADs the object and reads its real size back from storage. A client
that skips the upload and calls confirm anyway gets a 409, not a lesson pointing
at a URL that 404s for every student.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.media import MediaAsset, MediaKind, MediaStatus
from app.repositories.media_repository import MediaRepository
from app.schemas.media import (
    ALLOWED_CONTENT_TYPES,
    EXTENSION_BY_CONTENT_TYPE,
    MediaAssetRead,
    PlaybackTicket,
    UploadRequest,
    UploadTicket,
)
from app.services.storage import (
    ObjectNotFoundError,
    StorageError,
    StorageProvider,
)

logger = get_logger(__name__)


class MediaService:
    """Upload ticketing, confirmation, and playback URL issuance."""

    def __init__(
        self,
        repository: MediaRepository,
        storage: StorageProvider,
        settings: Settings,
    ) -> None:
        self._repo = repository
        self._storage = storage
        self._settings = settings

    # ── Policy ───────────────────────────────────────────────────────────────

    def max_bytes_for(self, kind: MediaKind) -> int:
        """The size ceiling for a kind of asset."""
        match kind:
            case MediaKind.LESSON_VIDEO:
                return self._settings.max_video_bytes
            case MediaKind.COURSE_COVER:
                return self._settings.max_image_bytes
            case MediaKind.LESSON_ATTACHMENT:
                return self._settings.max_document_bytes

    @staticmethod
    def build_storage_key(*, kind: MediaKind, content_type: str) -> str:
        """Generate an object key.

        Entirely server-side. A client-controlled key would allow overwriting
        another course's video, and a client-controlled extension would allow
        storing `.html` under a video content type. The date prefix keeps
        bucket listings navigable and gives lifecycle rules something to match.
        """
        extension = EXTENSION_BY_CONTENT_TYPE.get(content_type, "")
        now = datetime.now(UTC)
        return f"{kind.value}/{now:%Y/%m}/{uuid.uuid4().hex}{extension}"

    def _validate(self, payload: UploadRequest) -> None:
        """Reject a request that policy forbids, before issuing any credential."""
        allowed = ALLOWED_CONTENT_TYPES[payload.kind]
        if payload.content_type not in allowed:
            raise ValidationError(
                f"{payload.content_type} is not an accepted format for this upload.",
                details=[
                    {
                        "field": "content_type",
                        "message": f"Accepted: {', '.join(sorted(allowed))}.",
                    }
                ],
            )

        ceiling = self.max_bytes_for(payload.kind)
        if payload.size_bytes > ceiling:
            raise ValidationError(
                "That file is too large.",
                details=[
                    {
                        "field": "size_bytes",
                        "message": f"Maximum {ceiling // (1024 * 1024)} MB.",
                    }
                ],
            )

    # ── Upload ───────────────────────────────────────────────────────────────

    async def create_upload_ticket(
        self, payload: UploadRequest, *, uploaded_by: str
    ) -> UploadTicket:
        """Record intent and issue a presigned upload URL."""
        self._validate(payload)

        storage_key = self.build_storage_key(kind=payload.kind, content_type=payload.content_type)

        asset = MediaAsset(
            kind=payload.kind,
            status=MediaStatus.PENDING,
            storage_key=storage_key,
            original_filename=payload.filename,
            content_type=payload.content_type,
            # The client's claim, kept only so the pending row is informative.
            # Overwritten with the authoritative value on confirmation.
            size_bytes=payload.size_bytes,
            uploaded_by=uploaded_by,
        )
        self._repo.add(asset)
        await self._repo.session.flush()

        try:
            presigned = self._storage.create_presigned_upload(
                storage_key=storage_key,
                content_type=payload.content_type,
                expires_in_seconds=self._settings.media_upload_url_ttl_seconds,
            )
        except StorageError:
            # Nothing was issued, so the pending row would be a permanent orphan.
            await self._repo.session.rollback()
            raise

        await self._repo.session.commit()
        logger.info(
            "upload_ticket_issued",
            asset_id=str(asset.id),
            kind=payload.kind.value,
            storage_key=storage_key,
        )

        return UploadTicket(
            asset_id=asset.id,
            upload_url=presigned.url,
            method=presigned.method,
            headers=presigned.headers,
            expires_in_seconds=presigned.expires_in_seconds,
            storage_key=storage_key,
        )

    async def confirm_upload(
        self, asset_id: uuid.UUID, *, checksum: str | None = None
    ) -> MediaAssetRead:
        """Verify the object exists in storage, then mark the asset ready.

        Three failure modes are handled distinctly, because they need different
        responses from the client:

        * **Object absent** → the upload never completed. 409; the client should
          retry the upload, not the confirmation.
        * **Object oversized** → the presigned PUT could not enforce a size cap
          (only a POST policy can), so the file is deleted here and the asset
          marked failed. This is the compensating control for that gap.
        * **Already confirmed** → idempotent success. A duplicated confirm from a
          retried request must not be an error.
        """
        asset = await self._repo.get(asset_id)
        if asset is None:
            raise NotFoundError("That upload could not be found.")

        if asset.status is MediaStatus.READY:
            return MediaAssetRead.model_validate(asset)

        try:
            stored = self._storage.head(storage_key=asset.storage_key)
        except ObjectNotFoundError as exc:
            asset.status = MediaStatus.FAILED
            await self._repo.session.commit()
            logger.warning("upload_confirm_object_missing", asset_id=str(asset.id))
            raise ConflictError(
                "No uploaded file was found for this upload. Please try again."
            ) from exc

        ceiling = self.max_bytes_for(asset.kind)
        if stored.size_bytes > ceiling:
            # Delete first: an oversized object left in the bucket is billed for
            # and reachable by anyone who still holds the presigned URL.
            self._storage.delete(storage_key=asset.storage_key)
            asset.status = MediaStatus.FAILED
            await self._repo.session.commit()
            logger.warning(
                "upload_rejected_oversize",
                asset_id=str(asset.id),
                size_bytes=stored.size_bytes,
                ceiling=ceiling,
            )
            raise ValidationError(
                "That file is larger than the limit and has been discarded.",
                details=[
                    {
                        "field": "size_bytes",
                        "message": f"Maximum {ceiling // (1024 * 1024)} MB.",
                    }
                ],
            )

        asset.size_bytes = stored.size_bytes
        asset.status = MediaStatus.READY
        asset.confirmed_at = datetime.now(UTC)
        asset.checksum = checksum or stored.etag
        # The declared content type stays authoritative: it is what was bound
        # into the upload signature, and some backends do not echo one back.
        await self._repo.session.commit()

        logger.info("upload_confirmed", asset_id=str(asset.id), size_bytes=stored.size_bytes)
        return MediaAssetRead.model_validate(asset)

    # ── Retrieval ────────────────────────────────────────────────────────────

    async def get_ready_asset(self, asset_id: uuid.UUID) -> MediaAsset:
        """Load an asset that is confirmed present in storage.

        Raises:
            NotFoundError: No such asset.
            ConflictError: The asset exists but its upload never completed.
        """
        asset = await self._repo.get(asset_id)
        if asset is None:
            raise NotFoundError("That file could not be found.")
        if not asset.is_ready:
            raise ConflictError("That file has not finished uploading.")
        return asset

    def issue_playback_ticket(
        self, asset: MediaAsset, *, duration_seconds: int | None = None
    ) -> PlaybackTicket:
        """Mint a short-lived read URL for an asset.

        Authorisation happens **before** this is called — the URL itself carries
        no identity, so anyone holding it can read the object until it expires.
        That is why the TTL is minutes rather than hours, and why a fresh ticket
        is issued per view rather than cached.

        > When HLS lands, per-object URLs stop being workable: a stream is
        > hundreds of segments. The replacement is CDN signed cookies scoped to a
        > path prefix, which is why this returns a ticket object rather than a
        > bare string.
        """
        ttl = self._settings.media_playback_url_ttl_seconds
        url = self._storage.create_presigned_download(
            storage_key=asset.storage_key,
            expires_in_seconds=ttl,
            filename=(
                asset.original_filename if asset.kind is MediaKind.LESSON_ATTACHMENT else None
            ),
        )
        return PlaybackTicket(
            url=url,
            expires_in_seconds=ttl,
            content_type=asset.content_type,
            duration_seconds=duration_seconds,
        )

    async def delete_asset(self, asset_id: uuid.UUID) -> None:
        """Delete an asset and its object.

        Storage is cleared first. If the row were deleted first and the storage
        call then failed, the object would be unreachable *and* unbilled-for by
        anything that could ever clean it up.
        """
        asset = await self._repo.get(asset_id)
        if asset is None:
            raise NotFoundError("That file could not be found.")

        try:
            self._storage.delete(storage_key=asset.storage_key)
        except StorageError:
            logger.error("asset_delete_storage_failed", asset_id=str(asset.id))
            raise

        await self._repo.delete(asset)
        await self._repo.session.commit()
        logger.info("asset_deleted", asset_id=str(asset_id))
