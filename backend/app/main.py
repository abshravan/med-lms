"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.routers import auth, health

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of shared resources."""
    settings = get_settings()
    logger.info(
        "application_starting",
        environment=settings.environment,
        version=app.version,
    )
    await health.warm_dependencies()
    yield
    logger.info("application_stopping")
    await dispose_engine()
    await close_redis()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    A factory rather than a module-level singleton so tests can construct an app
    with overridden settings and dependencies without import-order games.
    """
    settings = settings or get_settings()

    configure_logging(
        debug=settings.debug,
        json_output=settings.environment != "development",
    )

    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        description=(
            "Domain API for the MedLMS medical education platform.\n\n"
            "Authentication uses bearer access tokens minted by Better Auth in the "
            "Next.js application. Obtain one from `GET /api/auth/token` on the web "
            "origin, then send it as `Authorization: Bearer <token>`."
        ),
        lifespan=lifespan,
        # Interactive docs are useful in every environment except production,
        # where an unauthenticated schema dump is free reconnaissance.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Order matters: RequestContextMiddleware is added last so it runs first and
    # every downstream log line — including CORS rejections — carries a request id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
