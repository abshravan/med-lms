"""S3-compatible storage (Cloudflare R2, MinIO, AWS S3).

R2 speaks the S3 API, so one client covers production, local MinIO, and the
in-process `moto` server the tests run against. The only differences are the
endpoint URL and the region.
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.logging import get_logger
from app.services.storage.base import (
    ObjectNotFoundError,
    PresignedUpload,
    StorageError,
    StoredObject,
)

logger = get_logger(__name__)

# Object keys are server-generated, so a not-found on HEAD means the client
# never completed its upload — not that a key was mistyped.
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class S3StorageProvider:
    """Presigned-URL storage backed by any S3-compatible service."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        public_base_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._public_base_url = public_base_url

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(
                # R2 only supports SigV4. Pinning it also avoids botocore
                # silently negotiating something a non-AWS endpoint rejects.
                signature_version="s3v4",
                # Presigned URLs must be path-style for MinIO and for R2's
                # account-scoped endpoint; virtual-host style would produce URLs
                # pointing at a subdomain that does not resolve.
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=15,
            ),
        )

    @property
    def name(self) -> str:
        return "s3"

    def create_presigned_upload(
        self, *, storage_key: str, content_type: str, expires_in_seconds: int
    ) -> PresignedUpload:
        """Issue a presigned PUT.

        `ContentType` is part of the signature, so the client must send exactly
        the type it declared. Without that binding, a client could obtain a URL
        for `video/mp4` and upload `text/html`, which the CDN would later serve
        back with a script-executing content type from the platform's own origin.

        > **Known limitation:** a presigned PUT cannot enforce a maximum object
        > size — only a POST policy can. The size is therefore verified on
        > confirmation and oversized objects are deleted. See
        > `MediaService.confirm_upload`.
        """
        try:
            url = self._client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": storage_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in_seconds,
                HttpMethod="PUT",
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error("presign_upload_failed", error=str(exc), key=storage_key)
            raise StorageError("Could not create an upload URL.") from exc

        return PresignedUpload(
            url=url,
            method="PUT",
            headers={"Content-Type": content_type},
            storage_key=storage_key,
            expires_in_seconds=expires_in_seconds,
        )

    def create_presigned_download(
        self, *, storage_key: str, expires_in_seconds: int, filename: str | None = None
    ) -> str:
        """Issue a presigned GET."""
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": storage_key}
        if filename is not None:
            # Quoted so a filename containing a comma or semicolon cannot split
            # the header into extra directives.
            safe = filename.replace('"', "").replace("\\", "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'

        try:
            url: str = self._client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expires_in_seconds,
                HttpMethod="GET",
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error("presign_download_failed", error=str(exc), key=storage_key)
            raise StorageError("Could not create a download URL.") from exc
        return url

    def head(self, *, storage_key: str) -> StoredObject:
        """Fetch object metadata, and prove the object actually exists."""
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=storage_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in _NOT_FOUND_CODES or status == 404:
                raise ObjectNotFoundError(storage_key) from exc
            logger.error("head_object_failed", error=str(exc), key=storage_key)
            raise StorageError("Could not read object metadata.") from exc
        except BotoCoreError as exc:
            raise StorageError("Could not read object metadata.") from exc

        return StoredObject(
            storage_key=storage_key,
            size_bytes=int(response.get("ContentLength", 0)),
            content_type=response.get("ContentType"),
            etag=str(response.get("ETag", "")).strip('"') or None,
        )

    def delete(self, *, storage_key: str) -> None:
        """Delete an object. S3 delete is already idempotent."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=storage_key)
        except (BotoCoreError, ClientError) as exc:
            logger.error("delete_object_failed", error=str(exc), key=storage_key)
            raise StorageError("Could not delete the object.") from exc

    def ping(self) -> bool:
        """Check the bucket is reachable."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except (BotoCoreError, ClientError):
            return False
