"""Filesystem storage for local development.

Lets the whole upload flow run with no cloud credentials and no MinIO container:
`docker compose up` and the media feature works.

The "presigned" URLs it issues are HMAC-signed links back to the API's own
`/api/v1/media/local/*` routes, which then read and write a directory on disk.
The signature carries the same expiry and key binding as the S3 version, so the
client code path is identical — the browser still PUTs directly to the returned
URL and never learns which backend is in use.

**Never enable this in production.** It has no redundancy, no CDN, and it puts
media on the API container's ephemeral disk. `Settings` rejects it when
`ENVIRONMENT=production`.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from app.core.logging import get_logger
from app.services.storage.base import (
    ObjectNotFoundError,
    PresignedUpload,
    StorageError,
    StoredObject,
)

logger = get_logger(__name__)


class LocalStorageProvider:
    """Development-only storage backed by a directory on disk."""

    def __init__(self, *, root: Path, base_url: str, signing_secret: str) -> None:
        self._root = root
        self._base_url = base_url.rstrip("/")
        self._secret = signing_secret.encode("utf-8")
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "local"

    # ── Path safety ──────────────────────────────────────────────────────────

    def _resolve(self, storage_key: str) -> Path:
        """Map a storage key onto a path, refusing anything outside the root.

        Keys are server-generated, so traversal should be impossible — but this
        is the function that turns a string into a filesystem write, and
        defence here costs nothing. `../` in a key would otherwise let a bug
        elsewhere overwrite arbitrary files.
        """
        candidate = (self._root / storage_key).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            logger.error("local_storage_traversal_blocked", key=storage_key)
            raise StorageError("Invalid storage key.")
        return candidate

    # ── Signing ──────────────────────────────────────────────────────────────

    def _sign(self, *, storage_key: str, method: str, expires_at: int) -> str:
        """Sign a key/method/expiry triple.

        The method is included so an upload URL cannot be replayed as a download
        URL, and vice versa.
        """
        payload = f"{method}\n{storage_key}\n{expires_at}".encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify(self, *, storage_key: str, method: str, expires_at: int, signature: str) -> bool:
        """Validate a signature. Used by the local upload/download routes."""
        if expires_at < int(time.time()):
            return False
        expected = self._sign(storage_key=storage_key, method=method, expires_at=expires_at)
        # Constant-time comparison: a byte-by-byte check leaks the correct
        # signature through timing, one character at a time.
        return hmac.compare_digest(expected, signature)

    def _signed_url(self, *, storage_key: str, method: str, expires_in_seconds: int) -> str:
        expires_at = int(time.time()) + expires_in_seconds
        signature = self._sign(storage_key=storage_key, method=method, expires_at=expires_at)
        query = urlencode({"expires": expires_at, "signature": signature})
        return f"{self._base_url}/api/v1/media/local/{quote(storage_key)}?{query}"

    # ── StorageProvider ──────────────────────────────────────────────────────

    def create_presigned_upload(
        self, *, storage_key: str, content_type: str, expires_in_seconds: int
    ) -> PresignedUpload:
        return PresignedUpload(
            url=self._signed_url(
                storage_key=storage_key, method="PUT", expires_in_seconds=expires_in_seconds
            ),
            method="PUT",
            headers={"Content-Type": content_type},
            storage_key=storage_key,
            expires_in_seconds=expires_in_seconds,
        )

    def create_presigned_download(
        self, *, storage_key: str, expires_in_seconds: int, filename: str | None = None
    ) -> str:
        # `filename` is ignored: the local route always serves inline, and this
        # backend exists only for development convenience.
        return self._signed_url(
            storage_key=storage_key, method="GET", expires_in_seconds=expires_in_seconds
        )

    def head(self, *, storage_key: str) -> StoredObject:
        path = self._resolve(storage_key)
        if not path.is_file():
            raise ObjectNotFoundError(storage_key)
        return StoredObject(
            storage_key=storage_key,
            size_bytes=path.stat().st_size,
            # The filesystem does not record a content type; the caller falls
            # back to what the client declared.
            content_type=None,
            etag=None,
        )

    def write(self, *, storage_key: str, data: bytes) -> None:
        """Write an object. Called by the local upload route, not by services."""
        path = self._resolve(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, *, storage_key: str) -> bytes:
        """Read an object. Called by the local download route."""
        path = self._resolve(storage_key)
        if not path.is_file():
            raise ObjectNotFoundError(storage_key)
        return path.read_bytes()

    def delete(self, *, storage_key: str) -> None:
        path = self._resolve(storage_key)
        path.unlink(missing_ok=True)

    def ping(self) -> bool:
        return self._root.is_dir()
