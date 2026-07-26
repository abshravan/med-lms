"""Redis client and the session-revocation denylist.

Two responsibilities, both auth-critical:

1. Caching the JWKS fetched from the identity service.
2. The revocation denylist that lets logout / ban / password-change take effect
   before a short-lived access token naturally expires.

**Fail-open policy for the denylist:** if Redis is unreachable, `is_revoked`
returns False rather than raising. Failing closed would turn a Redis blip into a
total API outage for every authenticated request. The residual exposure is
bounded by the access-token TTL (15 minutes). This is a deliberate, documented
tradeoff — see docs/architecture.md §3.3.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: aioredis.Redis | None = None

# Key namespaces. Centralised so nothing invents an ad-hoc key format.
SESSION_REVOKED_PREFIX = "revoked:sid:"
USER_REVOKED_PREFIX = "revoked:uid:"
JWKS_CACHE_KEY = "auth:jwks"


def get_redis() -> aioredis.Redis:
    """Return the process-wide Redis client, creating it on first use."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def set_redis_client(client: aioredis.Redis | None) -> None:
    """Override the client. Used by tests to inject a fake."""
    global _client
    _client = client


async def close_redis() -> None:
    """Close the connection pool. Called on application shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def is_revoked(*, session_id: str | None, user_id: str) -> bool:
    """Return True if either this session or the whole user has been revoked.

    Both keys are checked in a single pipeline round-trip. Fails open — see the
    module docstring.
    """
    keys = [f"{USER_REVOKED_PREFIX}{user_id}"]
    if session_id:
        keys.append(f"{SESSION_REVOKED_PREFIX}{session_id}")

    try:
        client = get_redis()
        async with client.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.exists(key)
            results = await pipe.execute()
        return any(bool(result) for result in results)
    except RedisError as exc:
        logger.warning(
            "revocation_check_unavailable",
            error=str(exc),
            user_id=user_id,
            policy="fail_open",
        )
        return False


async def revoke_session(session_id: str, *, ttl_seconds: int) -> None:
    """Deny-list a single session for `ttl_seconds`."""
    try:
        await get_redis().set(f"{SESSION_REVOKED_PREFIX}{session_id}", "1", ex=ttl_seconds)
    except RedisError as exc:
        logger.error("revoke_session_failed", error=str(exc), session_id=session_id)


async def revoke_user(user_id: str, *, ttl_seconds: int) -> None:
    """Deny-list every outstanding token for a user (ban / password change)."""
    try:
        await get_redis().set(f"{USER_REVOKED_PREFIX}{user_id}", "1", ex=ttl_seconds)
    except RedisError as exc:
        logger.error("revoke_user_failed", error=str(exc), user_id=user_id)


async def ping() -> bool:
    """Liveness probe for the health endpoint."""
    try:
        return bool(await get_redis().ping())
    except RedisError:
        return False
