"""Object-storage abstraction.

**Why bytes never pass through the API.** The obvious upload design — browser
POSTs the file to FastAPI, FastAPI forwards it to R2 — ties up a worker for the
entire duration of a multi-hundred-megabyte upload, holds it in memory or on
local disk, and makes upload throughput a function of API capacity. A single
lecture recording would occupy a request slot for minutes.

Instead the API issues a **short-lived presigned URL** and the browser uploads
directly to storage. The API's involvement is two small JSON round-trips, so
upload capacity scales with the object store rather than with the API.

This protocol is the seam. `S3StorageProvider` covers Cloudflare R2 in
production and MinIO locally; `LocalStorageProvider` covers development with no
credentials at all. A future migration to a different vendor is a new
implementation of five methods, not a change to any service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """A short-lived credential permitting exactly one object write."""

    url: str
    """Absolute URL the client sends the object to."""

    method: str
    """HTTP method to use. `PUT` for every provider currently implemented."""

    headers: dict[str, str]
    """Headers the client MUST send verbatim — they are part of the signature."""

    storage_key: str
    """Server-generated object key. Never client-controlled."""

    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Metadata about an object that exists in storage."""

    storage_key: str
    size_bytes: int
    content_type: str | None
    etag: str | None


class StorageError(RuntimeError):
    """Raised when the storage backend cannot complete an operation."""


class ObjectNotFoundError(StorageError):
    """Raised when an object does not exist."""


@runtime_checkable
class StorageProvider(Protocol):
    """The contract every storage backend implements."""

    @property
    def name(self) -> str:
        """Short identifier, used in logs and health output."""
        ...

    def create_presigned_upload(
        self,
        *,
        storage_key: str,
        content_type: str,
        expires_in_seconds: int,
    ) -> PresignedUpload:
        """Issue a credential allowing a single write to `storage_key`.

        The content type is bound into the signature, so a client that promised
        `video/mp4` cannot upload an HTML file to the same key and have it served
        back with a script-executing content type.
        """
        ...

    def create_presigned_download(
        self, *, storage_key: str, expires_in_seconds: int, filename: str | None = None
    ) -> str:
        """Issue a short-lived read URL.

        `filename` sets `Content-Disposition` so downloaded PDFs keep a sensible
        name instead of the opaque storage key.
        """
        ...

    def head(self, *, storage_key: str) -> StoredObject:
        """Return metadata for an object.

        Raises:
            ObjectNotFoundError: The object does not exist.
        """
        ...

    def delete(self, *, storage_key: str) -> None:
        """Remove an object. Succeeds if it is already absent."""
        ...

    def ping(self) -> bool:
        """Return True if the backend is reachable. Used by the readiness probe."""
        ...
