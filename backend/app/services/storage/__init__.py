"""Storage provider selection.

One factory, cached per process, so the choice of backend is made once at boot
from configuration rather than threaded through call sites.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.storage.base import (
    ObjectNotFoundError,
    PresignedUpload,
    StorageError,
    StorageProvider,
    StoredObject,
)
from app.services.storage.local import LocalStorageProvider
from app.services.storage.s3 import S3StorageProvider

logger = get_logger(__name__)

_override: StorageProvider | None = None


@lru_cache(maxsize=1)
def _build_provider() -> StorageProvider:
    """Construct the configured provider."""
    settings = get_settings()

    if settings.storage_backend == "s3":
        logger.info("storage_backend_selected", backend="s3", bucket=settings.s3_bucket)
        return S3StorageProvider(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
        )

    # `Settings` already refuses this combination in production.
    logger.warning("storage_backend_selected", backend="local", note="development only")
    return LocalStorageProvider(
        root=Path(settings.media_local_root),
        base_url=settings.media_public_base_url,
        # Reuses the JWT audience only as a domain separator; the local backend
        # is never a production security boundary.
        signing_secret=f"{settings.auth_audience}:{settings.s3_secret_access_key or 'dev'}",
    )


def get_storage_provider() -> StorageProvider:
    """Return the active provider, honouring any test override."""
    if _override is not None:
        return _override
    return _build_provider()


def set_storage_provider(provider: StorageProvider | None) -> None:
    """Override the provider. Used by tests to inject a moto- or tmp-backed one."""
    global _override
    _override = provider
    _build_provider.cache_clear()


__all__ = [
    "LocalStorageProvider",
    "ObjectNotFoundError",
    "PresignedUpload",
    "S3StorageProvider",
    "StorageError",
    "StorageProvider",
    "StoredObject",
    "get_storage_provider",
    "set_storage_provider",
]
