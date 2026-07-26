"""Token verification tests.

These are the highest-value tests in the codebase: every one of them describes a
way an attacker could try to get past authentication.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import respx
from httpx import Response

from app.core.exceptions import (
    TokenExpiredError,
    TokenInvalidError,
    UpstreamUnavailableError,
)
from app.core.security import get_jwks, reset_jwks_cache, verify_access_token
from tests.conftest import TEST_JWKS_URL, TokenFactory


async def test_valid_token_yields_claims(
    tokens: TokenFactory, jwks_endpoint: respx.MockRouter
) -> None:
    token = tokens.create(user_id="user_1", role="admin", session_id="sess-9")

    claims = await verify_access_token(token)

    assert claims.user_id == "user_1"
    assert claims.role == "admin"
    assert claims.session_id == "sess-9"
    assert claims.email_verified is True


async def test_expired_token_is_rejected(
    tokens: TokenFactory, jwks_endpoint: respx.MockRouter
) -> None:
    token = tokens.create(user_id="user_1", expires_in=timedelta(minutes=-5))

    with pytest.raises(TokenExpiredError):
        await verify_access_token(token)


async def test_token_for_another_audience_is_rejected(
    tokens: TokenFactory, jwks_endpoint: respx.MockRouter
) -> None:
    """A token minted for a different resource server must not be accepted here."""
    token = tokens.create(user_id="user_1", audience="some-other-api")

    with pytest.raises(TokenInvalidError):
        await verify_access_token(token)


async def test_token_from_unknown_issuer_is_rejected(
    tokens: TokenFactory, jwks_endpoint: respx.MockRouter
) -> None:
    token = tokens.create(user_id="user_1", issuer="https://evil.example")

    with pytest.raises(TokenInvalidError):
        await verify_access_token(token)


async def test_token_signed_by_a_foreign_key_is_rejected(
    jwks_endpoint: respx.MockRouter,
) -> None:
    """A correctly-shaped token signed with a key we do not publish must fail.

    The attacker's key id deliberately matches the legitimate one, so this also
    covers the case where `kid` is spoofed.
    """
    attacker = TokenFactory(key_id="test-key-1")
    token = attacker.create(user_id="user_1")

    with pytest.raises(TokenInvalidError):
        await verify_access_token(token)


async def test_unsigned_token_is_rejected(jwks_endpoint: respx.MockRouter) -> None:
    """The `alg: none` attack: a token with no signature at all."""
    import jwt

    token = jwt.encode(
        {"sub": "user_1", "iss": "http://localhost:3000", "aud": "med-lms-api", "exp": 9e9},
        key="",
        algorithm="none",
    )

    with pytest.raises(TokenInvalidError):
        await verify_access_token(token)


async def test_hs256_token_is_rejected(jwks_endpoint: respx.MockRouter) -> None:
    """Algorithm confusion: an HS256 token must not be verified against an EC key."""
    import jwt

    token = jwt.encode(
        {"sub": "user_1", "iss": "http://localhost:3000", "aud": "med-lms-api", "exp": 9e9},
        key="a-shared-secret",
        algorithm="HS256",
        headers={"kid": "test-key-1"},
    )

    with pytest.raises(TokenInvalidError):
        await verify_access_token(token)


async def test_malformed_token_is_rejected(jwks_endpoint: respx.MockRouter) -> None:
    with pytest.raises(TokenInvalidError):
        await verify_access_token("this-is-not-a-jwt")


async def test_token_without_subject_is_rejected(
    tokens: TokenFactory, jwks_endpoint: respx.MockRouter
) -> None:
    """`sub` is the only claim we cannot operate without."""
    import jwt

    token = jwt.encode(
        {"iss": "http://localhost:3000", "aud": "med-lms-api", "exp": 9e9},
        tokens._private_key,  # noqa: SLF001 - exercising a malformed-token path
        algorithm="ES256",
        headers={"kid": tokens.key_id},
    )

    with pytest.raises(TokenInvalidError):
        await verify_access_token(token)


async def test_unknown_role_defaults_to_student(
    tokens: TokenFactory, jwks_endpoint: respx.MockRouter
) -> None:
    """An unrecognised role claim must never widen access."""
    token = tokens.create(user_id="user_1", role="superuser")
    claims = await verify_access_token(token)

    # The raw claim is preserved, but authorisation reads the database-backed
    # role, and `_coerce_role` downgrades anything unknown.
    from app.models.profile import UserRole
    from app.services.auth_service import _coerce_role

    assert _coerce_role(claims.role) is UserRole.STUDENT


# ── JWKS caching and rotation ────────────────────────────────────────────────


async def test_jwks_is_fetched_once_then_cached(
    tokens: TokenFactory, jwks_endpoint: respx.MockRouter
) -> None:
    """Verification must not hit the identity service on every request."""
    token = tokens.create(user_id="user_1")

    for _ in range(5):
        await verify_access_token(token)

    assert jwks_endpoint.routes[0].call_count == 1


async def test_unknown_kid_triggers_a_single_refresh(tokens: TokenFactory) -> None:
    """A rotated key should be picked up without an operator intervening."""
    rotated = TokenFactory(key_id="test-key-2")
    token = rotated.create(user_id="user_1")

    with respx.mock(assert_all_called=False) as router:
        route = router.get(TEST_JWKS_URL)
        # First response is the stale key set; the forced refresh returns the new one.
        route.side_effect = [
            Response(200, json=tokens.jwks),
            Response(200, json=rotated.jwks),
        ]
        claims = await verify_access_token(token)

    assert claims.user_id == "user_1"
    assert route.call_count == 2


async def test_jwks_fetch_failure_surfaces_as_upstream_unavailable() -> None:
    """A down identity service must not be reported as an invalid token.

    Distinguishing these matters operationally: 401 sends users to re-login,
    503 tells them (and the dashboard) to wait.
    """
    reset_jwks_cache()
    with respx.mock(assert_all_called=False) as router:
        router.get(TEST_JWKS_URL).mock(return_value=Response(500))
        with pytest.raises(UpstreamUnavailableError):
            await get_jwks()


async def test_empty_jwks_is_treated_as_unavailable() -> None:
    reset_jwks_cache()
    with respx.mock(assert_all_called=False) as router:
        router.get(TEST_JWKS_URL).mock(return_value=Response(200, json={"keys": []}))
        with pytest.raises(UpstreamUnavailableError):
            await get_jwks()
