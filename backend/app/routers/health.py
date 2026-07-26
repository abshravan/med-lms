"""Liveness and readiness endpoints.

Split deliberately: an orchestrator restarting a container because Redis is
briefly unreachable makes an outage worse. Liveness answers "is this process
alive", readiness answers "should it receive traffic".
"""

from typing import Literal

from fastapi import Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.core.database import get_session_factory
from app.core.dependencies import SessionDep
from app.core.envelope import create_router
from app.core.logging import get_logger
from app.core.redis import ping as redis_ping
from app.schemas.common import SuccessResponse

logger = get_logger(__name__)

router = create_router(tags=["health"])


class LivenessStatus(BaseModel):
    """Process-level health."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class DependencyStatus(BaseModel):
    """Per-dependency readiness detail."""

    model_config = ConfigDict(extra="forbid")

    database: bool
    redis: bool


class ReadinessStatus(BaseModel):
    """Aggregate readiness."""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    dependencies: DependencyStatus


@router.get("/health", response_model=SuccessResponse[LivenessStatus], summary="Liveness")
async def liveness() -> LivenessStatus:
    """Return ok if the process is serving requests. Touches no dependency."""
    return LivenessStatus(status="ok")


@router.get("/ready", response_model=SuccessResponse[ReadinessStatus], summary="Readiness")
async def readiness(session: SessionDep, response: Response) -> ReadinessStatus:
    """Check that Postgres and Redis are reachable.

    Returns 503 when either is down so the load balancer stops routing here,
    while the container itself stays up.
    """
    database_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        logger.warning("readiness_database_failed", error=str(exc))
        database_ok = False

    redis_ok = await redis_ping()
    ready = database_ok and redis_ok

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessStatus(
        ready=ready,
        dependencies=DependencyStatus(database=database_ok, redis=redis_ok),
    )


async def warm_dependencies() -> None:
    """Open a connection at startup so the first real request is not the probe.

    Failure is logged, not fatal: the API should start and report unready rather
    than crash-loop while Postgres finishes booting.
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        logger.info("database_connection_warmed")
    except Exception as exc:  # noqa: BLE001 - startup must be resilient
        logger.warning("database_warmup_failed", error=str(exc))
