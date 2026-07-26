"""Application configuration.

Every setting is sourced from the environment and validated at import time.
A missing or malformed secret fails the boot loudly — it never silently falls
back to an insecure default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
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
