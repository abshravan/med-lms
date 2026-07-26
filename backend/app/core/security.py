"""Access-token verification against the Better Auth JWKS.

The identity service (Better Auth, running inside the Next.js app) signs
short-lived ES256 access tokens. This module verifies them **offline**: the only
network call is the periodic JWKS fetch, not one call per request. That is what
makes authentication scale horizontally without adding load to the identity
service.

Layered caching, fastest first:

1. Process-local cache (no I/O).
2. Redis, shared by every API container (one fetch per cluster per TTL).
3. HTTP fetch from the identity service.

An unknown `kid` triggers exactly one forced refresh, guarded by a cooldown so a
burst of requests carrying bogus tokens cannot stampede the identity service.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx
import jwt
from jwt import PyJWK, PyJWKSet
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.exceptions import (
    TokenExpiredError,
    TokenInvalidError,
    UpstreamUnavailableError,
)
from app.core.logging import get_logger
from app.core.redis import JWKS_CACHE_KEY, get_redis

logger = get_logger(__name__)

ALLOWED_ALGORITHMS: Final[tuple[str, ...]] = ("ES256",)
"""Algorithms are pinned explicitly.

Never derive the algorithm from the token header alone — that is the classic
`alg: none` / HS256-confusion vulnerability. The verifier decides, not the token.
"""

FORCED_REFRESH_COOLDOWN_SECONDS: Final[int] = 30


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Validated claims extracted from an access token.

    Frozen: once verified, claims are facts about the request and must not be
    mutated by downstream code.
    """

    user_id: str
    email: str | None
    email_verified: bool
    role: str
    session_id: str | None
    expires_at: int
    raw: dict[str, Any]


@dataclass
class _JwksCache:
    """Process-local JWKS cache state."""

    key_set: PyJWKSet | None = None
    fetched_at: float = 0.0
    last_forced_refresh: float = 0.0


_cache = _JwksCache()


def reset_jwks_cache() -> None:
    """Clear the process-local cache. Used by tests."""
    global _cache
    _cache = _JwksCache()


async def _fetch_jwks_from_identity_service() -> dict[str, Any]:
    """Fetch the JWKS document over HTTP."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.auth_jwks_http_timeout_seconds) as client:
            response = await client.get(settings.auth_jwks_url)
            response.raise_for_status()
            document: dict[str, Any] = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.error("jwks_fetch_failed", error=str(exc), url=settings.auth_jwks_url)
        raise UpstreamUnavailableError(
            "Unable to reach the identity service to verify your session."
        ) from exc

    if not isinstance(document.get("keys"), list) or not document["keys"]:
        logger.error("jwks_document_empty", url=settings.auth_jwks_url)
        raise UpstreamUnavailableError("The identity service returned no signing keys.")

    return document


async def _read_jwks_from_redis() -> dict[str, Any] | None:
    """Read the cached JWKS document from Redis, or None on miss/error."""
    try:
        cached = await get_redis().get(JWKS_CACHE_KEY)
    except RedisError as exc:
        logger.warning("jwks_cache_read_failed", error=str(exc))
        return None
    if not cached:
        return None
    try:
        document: dict[str, Any] = json.loads(cached)
        return document
    except json.JSONDecodeError:
        logger.warning("jwks_cache_corrupt")
        return None


async def _write_jwks_to_redis(document: dict[str, Any]) -> None:
    """Cache the JWKS document in Redis. Best-effort."""
    settings = get_settings()
    try:
        await get_redis().set(
            JWKS_CACHE_KEY,
            json.dumps(document),
            ex=settings.auth_jwks_cache_ttl_seconds,
        )
    except RedisError as exc:
        logger.warning("jwks_cache_write_failed", error=str(exc))


async def get_jwks(*, force_refresh: bool = False) -> PyJWKSet:
    """Return the signing key set, honouring the cache layers.

    Args:
        force_refresh: Bypass both caches. Rate-limited internally.
    """
    settings = get_settings()
    now = time.monotonic()

    if force_refresh:
        if now - _cache.last_forced_refresh < FORCED_REFRESH_COOLDOWN_SECONDS:
            # Someone already refreshed a moment ago; serving the current set is
            # correct and stops a bogus-kid flood from hammering upstream.
            if _cache.key_set is not None:
                return _cache.key_set
        else:
            _cache.last_forced_refresh = now
    else:
        fresh = now - _cache.fetched_at < settings.auth_jwks_cache_ttl_seconds
        if _cache.key_set is not None and fresh:
            return _cache.key_set

        document = await _read_jwks_from_redis()
        if document is not None:
            key_set = PyJWKSet.from_dict(document)
            _cache.key_set = key_set
            _cache.fetched_at = now
            return key_set

    document = await _fetch_jwks_from_identity_service()
    await _write_jwks_to_redis(document)

    key_set = PyJWKSet.from_dict(document)
    _cache.key_set = key_set
    _cache.fetched_at = now
    logger.info("jwks_refreshed", key_count=len(document["keys"]))
    return key_set


def _select_key(key_set: PyJWKSet, kid: str | None) -> PyJWK | None:
    """Find the signing key matching `kid`.

    When the token carries no `kid` and the set holds exactly one key, that key
    is unambiguous and is used. With multiple keys and no `kid` the token is
    rejected rather than guessed at.
    """
    keys = list(key_set.keys)
    if kid is None:
        return keys[0] if len(keys) == 1 else None
    for key in keys:
        if key.key_id == kid:
            return key
    return None


async def verify_access_token(token: str) -> TokenClaims:
    """Verify an access token and return its claims.

    Raises:
        TokenExpiredError: Signature valid but `exp` has passed.
        TokenInvalidError: Malformed, wrong signature, wrong issuer/audience, or
            signed by an unknown key.
        UpstreamUnavailableError: The key set could not be obtained at all.
    """
    settings = get_settings()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        logger.info("token_header_unreadable", error=str(exc))
        raise TokenInvalidError() from exc

    algorithm = header.get("alg")
    if algorithm not in ALLOWED_ALGORITHMS:
        logger.warning("token_algorithm_rejected", algorithm=algorithm)
        raise TokenInvalidError()

    kid = header.get("kid")
    key_set = await get_jwks()
    signing_key = _select_key(key_set, kid)

    if signing_key is None:
        # Most likely an ordinary key rotation: refresh once, then give up.
        key_set = await get_jwks(force_refresh=True)
        signing_key = _select_key(key_set, kid)

    if signing_key is None:
        logger.warning("token_signing_key_unknown", kid=kid)
        raise TokenInvalidError("Your session was signed with an unrecognised key.")

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=list(ALLOWED_ALGORITHMS),
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            leeway=settings.auth_leeway_seconds,
            options={
                "require": ["exp", "sub", "iss", "aud"],
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
                "verify_signature": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidAudienceError as exc:
        logger.warning("token_audience_mismatch", expected=settings.auth_audience)
        raise TokenInvalidError("This token was not issued for this API.") from exc
    except jwt.InvalidIssuerError as exc:
        logger.warning("token_issuer_mismatch", expected=settings.auth_issuer)
        raise TokenInvalidError("This token was issued by an unknown provider.") from exc
    except jwt.PyJWTError as exc:
        logger.info("token_verification_failed", error=type(exc).__name__)
        raise TokenInvalidError() from exc

    return _to_claims(payload)


def _to_claims(payload: dict[str, Any]) -> TokenClaims:
    """Map a verified payload onto TokenClaims.

    Better Auth nests user fields differently depending on plugin configuration,
    so both the flat and `user`-nested shapes are tolerated. `sub` is the only
    field treated as mandatory — everything else has a safe default.
    """
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise TokenInvalidError("Token is missing a subject claim.")

    nested = payload.get("user")
    user: dict[str, Any] = nested if isinstance(nested, dict) else payload

    role = user.get("role") or payload.get("role") or "student"

    return TokenClaims(
        user_id=subject,
        email=_as_optional_str(user.get("email")),
        email_verified=bool(user.get("emailVerified") or user.get("email_verified")),
        role=str(role),
        session_id=_as_optional_str(payload.get("sid") or payload.get("session_id")),
        expires_at=int(payload["exp"]),
        raw=payload,
    )


def _as_optional_str(value: object) -> str | None:
    """Coerce a claim to str, treating anything non-string as absent."""
    return value if isinstance(value, str) and value else None
