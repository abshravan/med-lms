"""Application configuration.

Every setting is sourced from the environment and validated at import time.
A missing or malformed secret fails the boot loudly — it never silently falls
back to an insecure default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    """Runtime settings for the domain API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────────────────
    environment: Environment = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    project_name: str = "MedLMS API"

    # ── Datastores ───────────────────────────────────────────────────────────
    database_url: PostgresDsn
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_echo: bool = False

    redis_url: RedisDsn

    # ── Identity bridge (Better Auth in the Next.js app) ─────────────────────
    auth_jwks_url: str = Field(
        description="Absolute URL of the Better Auth JWKS endpoint, "
        "e.g. http://web:3000/api/auth/jwks",
    )
    auth_issuer: str = Field(
        description="Expected `iss` claim — the Better Auth base URL.",
    )
    auth_audience: str = Field(
        default="med-lms-api",
        description="Expected `aud` claim on access tokens.",
    )
    auth_jwks_cache_ttl_seconds: int = Field(default=600, ge=30, le=86_400)
    auth_jwks_http_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    auth_leeway_seconds: int = Field(
        default=10,
        ge=0,
        le=120,
        description="Clock-skew tolerance when validating exp/nbf.",
    )

    # ── Media storage ────────────────────────────────────────────────────────
    storage_backend: Literal["s3", "local"] = Field(
        default="local",
        description="`s3` for Cloudflare R2/MinIO/AWS; `local` for development only.",
    )

    s3_bucket: str = "med-lms-media"
    s3_endpoint_url: str | None = Field(
        default=None,
        description="R2/MinIO endpoint. Leave unset for real AWS S3.",
    )
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "auto"

    media_local_root: str = Field(
        default="/tmp/med-lms-media",  # noqa: S108 - development backend only
        description="Directory used by the `local` backend.",
    )
    media_public_base_url: str = Field(
        default="http://localhost:8000",
        description="Public base URL of this API, used to build local signed URLs.",
    )

    # Long enough for a slow connection to start a large upload, short enough
    # that a leaked URL is not a standing write grant.
    media_upload_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    # Short: a playback URL is re-issued per view, and a leaked one should expire
    # before it is worth sharing.
    media_playback_url_ttl_seconds: int = Field(default=300, ge=60, le=3600)

    max_video_bytes: int = Field(default=2 * 1024**3, gt=0)
    max_image_bytes: int = Field(default=10 * 1024**2, gt=0)
    max_document_bytes: int = Field(default=50 * 1024**2, gt=0)

    @model_validator(mode="after")
    def _validate_storage(self) -> Settings:
        """Reject storage configurations that cannot work.

        The production check is the important one: the local backend writes to
        the API container's ephemeral disk, so a production deploy that fell back
        to it would lose every upload on the next restart — silently, and only
        discovered when a student reported a dead video.
        """
        if self.environment == "production" and self.storage_backend == "local":
            raise ValueError(
                "STORAGE_BACKEND=local is development-only; media would be lost "
                "on container restart. Set STORAGE_BACKEND=s3 in production."
            )
        if self.storage_backend == "s3" and not (
            self.s3_access_key_id and self.s3_secret_access_key
        ):
            raise ValueError(
                "STORAGE_BACKEND=s3 requires S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY."
            )
        return self

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Allow a comma-separated string so `.env` files stay readable."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sqlalchemy_dsn(self) -> str:
        """asyncpg-flavoured DSN.

        Accepts the plain `postgresql://` form in the environment (which is what
        every other tool in the stack understands) and adapts it for the async
        driver here, so there is exactly one DATABASE_URL across all services.
        """
        dsn = str(self.database_url)
        if dsn.startswith("postgresql+"):
            return dsn
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Cached so validation runs exactly once."""
    return Settings()
