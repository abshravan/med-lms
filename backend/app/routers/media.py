"""Media upload routes.

Admin-only, with the role guard declared once on the router — the same pattern as
`admin_courses`.

The local-development upload/download routes at the bottom are the one exception:
they authenticate with an HMAC signature rather than a bearer token, because the
browser PUTs to them directly with no `Authorization` header, exactly as it would
to R2.
"""

import uuid

from fastapi import Depends, Request, Response, status

from app.core.dependencies import CurrentUserDep, MediaServiceDep, require_role
from app.core.envelope import create_router
from app.core.exceptions import NotFoundError, UnauthenticatedError
from app.models.profile import UserRole
from app.schemas.common import SuccessResponse
from app.schemas.media import (
    ConfirmUploadRequest,
    MediaAssetRead,
    UploadRequest,
    UploadTicket,
)
from app.services.storage import (
    LocalStorageProvider,
    ObjectNotFoundError,
    get_storage_provider,
)

router = create_router(
    prefix="/admin/media",
    tags=["admin: media"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.post(
    "/uploads",
    response_model=SuccessResponse[UploadTicket],
    status_code=status.HTTP_201_CREATED,
    summary="Request a direct-upload URL",
)
async def create_upload(
    payload: UploadRequest,
    service: MediaServiceDep,
    user: CurrentUserDep,
) -> UploadTicket:
    """Issue a short-lived URL the client uploads to directly.

    The API never receives the file. Send the bytes to `upload_url` with the
    returned `method` and `headers` exactly as given — the headers are part of
    the signature — then call the confirm endpoint.
    """
    return await service.create_upload_ticket(payload, uploaded_by=user.user_id)


@router.post(
    "/uploads/{asset_id}/confirm",
    response_model=SuccessResponse[MediaAssetRead],
    summary="Confirm an upload finished",
)
async def confirm_upload(
    asset_id: uuid.UUID,
    payload: ConfirmUploadRequest,
    service: MediaServiceDep,
) -> MediaAssetRead:
    """Verify the object exists in storage and mark the asset ready.

    Idempotent. Returns `409` if no object was found — the upload itself should
    be retried, not this call.
    """
    return await service.confirm_upload(asset_id, checksum=payload.checksum)


@router.delete(
    "/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an asset and its stored object",
)
async def delete_asset(asset_id: uuid.UUID, service: MediaServiceDep) -> Response:
    """Delete an asset. Any lesson or course referencing it is set to null."""
    await service.delete_asset(asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Local development backend ────────────────────────────────────────────────
#
# These exist only when STORAGE_BACKEND=local. They stand in for R2's own
# endpoints so the client code path is identical in development, and they are
# mounted on a separate router with **no bearer-token guard** — the browser PUTs
# to them with no Authorization header, so the HMAC signature in the query string
# is the credential.

local_router = create_router(prefix="/media/local", tags=["media: local"])


def _require_local_provider() -> LocalStorageProvider:
    """Resolve the local provider, or 404 when another backend is configured."""
    provider = get_storage_provider()
    if not isinstance(provider, LocalStorageProvider):
        # Not an error condition — the route simply does not exist for S3.
        raise NotFoundError("Not found.")
    return provider


@local_router.put(
    "/{storage_key:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Development-only object upload",
    include_in_schema=False,
)
async def local_upload(
    storage_key: str, request: Request, expires: int = 0, signature: str = ""
) -> Response:
    """Accept an object for the local backend, if the signature is valid."""
    provider = _require_local_provider()
    if not provider.verify(
        storage_key=storage_key, method="PUT", expires_at=expires, signature=signature
    ):
        raise UnauthenticatedError("That upload link is invalid or has expired.")

    provider.write(storage_key=storage_key, data=await request.body())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@local_router.get(
    "/{storage_key:path}",
    summary="Development-only object download",
    include_in_schema=False,
)
async def local_download(storage_key: str, expires: int = 0, signature: str = "") -> Response:
    """Serve an object from the local backend, if the signature is valid."""
    provider = _require_local_provider()
    if not provider.verify(
        storage_key=storage_key, method="GET", expires_at=expires, signature=signature
    ):
        raise UnauthenticatedError("That link is invalid or has expired.")

    try:
        data = provider.read(storage_key=storage_key)
    except ObjectNotFoundError as exc:
        raise NotFoundError("That file could not be found.") from exc

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            # Never let a stored object be interpreted as something executable
            # by the browser, whatever its bytes look like.
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=60",
        },
    )
