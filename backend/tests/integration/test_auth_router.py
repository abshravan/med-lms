"""End-to-end tests for the auth routes.

Every test goes through the real HTTP stack: middleware, dependency chain, token
verification, service, repository, Postgres. The only stand-ins are the JWKS
endpoint and Redis.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import USER_REVOKED_PREFIX
from app.models.profile import AuthAuditLog, AuthEvent, UserProfile, UserRole
from tests.conftest import TokenFactory


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_success(payload: dict[str, Any]) -> dict[str, Any]:
    """Assert the success envelope and return `data`."""
    assert payload["success"] is True
    assert payload["message"] == ""
    assert "meta" in payload and payload["meta"]["request_id"]
    data: dict[str, Any] = payload["data"]
    return data


def assert_error(payload: dict[str, Any], code: str) -> None:
    """Assert the error envelope carries the expected stable code."""
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == code
    assert payload["message"]


# ── GET /auth/me ─────────────────────────────────────────────────────────────


async def test_me_provisions_a_profile_on_first_request(
    client: AsyncClient,
    session: AsyncSession,
    tokens: TokenFactory,
    make_user: Any,
) -> None:
    """A user who registered through Better Auth gets their profile lazily."""
    user = await make_user(name="Grace Hopper", role="student")

    response = await client.get(
        "/api/v1/auth/me", headers=auth_header(tokens.create(user_id=user.id))
    )

    assert response.status_code == 200
    data = assert_success(response.json())
    assert data["user_id"] == user.id
    assert data["email"] == user.email
    assert data["role"] == "student"
    assert data["display_name"] == "Grace Hopper"
    assert data["onboarding_completed"] is False

    profile = await session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    assert profile is not None


async def test_me_is_idempotent_across_repeat_requests(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """Lazy provisioning must not fail or duplicate on the second call."""
    user = await make_user()
    token = tokens.create(user_id=user.id)

    first = await client.get("/api/v1/auth/me", headers=auth_header(token))
    second = await client.get("/api/v1/auth/me", headers=auth_header(token))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["user_id"] == second.json()["data"]["user_id"]


async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert_error(response.json(), "UNAUTHENTICATED")


async def test_me_rejects_a_revoked_session(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, fake_redis: Any
) -> None:
    """Signing out must invalidate an already-issued token immediately."""
    user = await make_user()
    token = tokens.create(user_id=user.id, session_id="sess-revoked")
    await fake_redis.set("revoked:sid:sess-revoked", "1", ex=900)

    response = await client.get("/api/v1/auth/me", headers=auth_header(token))

    assert response.status_code == 401
    assert_error(response.json(), "SESSION_REVOKED")


async def test_me_rejects_a_banned_account_and_revokes_its_tokens(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, fake_redis: Any
) -> None:
    """A ban applied in the admin tool must take effect on the next request."""
    user = await make_user(banned=True)

    response = await client.get(
        "/api/v1/auth/me", headers=auth_header(tokens.create(user_id=user.id))
    )

    assert response.status_code == 403
    assert_error(response.json(), "ACCOUNT_BANNED")
    # Every other outstanding token for this user is now dead too.
    assert await fake_redis.exists(f"{USER_REVOKED_PREFIX}{user.id}")


async def test_me_rejects_a_token_for_a_deleted_user(
    client: AsyncClient, tokens: TokenFactory
) -> None:
    """A validly signed token naming a user that no longer exists."""
    response = await client.get(
        "/api/v1/auth/me", headers=auth_header(tokens.create(user_id="user_gone"))
    )

    assert response.status_code == 404
    assert_error(response.json(), "NOT_FOUND")


async def test_me_is_available_to_unverified_users(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """The client must be able to render the 'verify your email' state."""
    user = await make_user(email_verified=False)

    response = await client.get(
        "/api/v1/auth/me",
        headers=auth_header(tokens.create(user_id=user.id, email_verified=False)),
    )

    assert response.status_code == 200
    assert assert_success(response.json())["email_verified"] is False


# ── PATCH /auth/me ───────────────────────────────────────────────────────────


async def test_update_profile_applies_changes_and_completes_onboarding(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(with_profile=True)

    response = await client.patch(
        "/api/v1/auth/me",
        headers=auth_header(tokens.create(user_id=user.id)),
        json={
            "display_name": "Dr. Ada",
            "institution": "AIIMS Delhi",
            "year_of_study": 3,
            "timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 200
    data = assert_success(response.json())
    assert data["display_name"] == "Dr. Ada"
    assert data["institution"] == "AIIMS Delhi"
    assert data["year_of_study"] == 3
    assert data["timezone"] == "Asia/Kolkata"
    assert data["onboarding_completed"] is True


async def test_update_profile_ignores_absent_fields(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """A PATCH must not null out fields the client never mentioned."""
    user = await make_user(with_profile=True)
    token = tokens.create(user_id=user.id)

    await client.patch(
        "/api/v1/auth/me",
        headers=auth_header(token),
        json={"institution": "KMC Manipal", "specialization": "Cardiology"},
    )
    response = await client.patch(
        "/api/v1/auth/me", headers=auth_header(token), json={"year_of_study": 2}
    )

    data = assert_success(response.json())
    assert data["institution"] == "KMC Manipal"
    assert data["specialization"] == "Cardiology"
    assert data["year_of_study"] == 2


async def test_update_profile_rejects_an_out_of_range_year(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(with_profile=True)

    response = await client.patch(
        "/api/v1/auth/me",
        headers=auth_header(tokens.create(user_id=user.id)),
        json={"year_of_study": 99},
    )

    assert response.status_code == 422
    payload = response.json()
    assert_error(payload, "VALIDATION_ERROR")
    # The field path is relative to the submitted body so the frontend can map it
    # straight onto the form control.
    assert payload["error"]["details"][0]["field"] == "year_of_study"


async def test_update_profile_rejects_an_unknown_timezone(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(with_profile=True)

    response = await client.patch(
        "/api/v1/auth/me",
        headers=auth_header(tokens.create(user_id=user.id)),
        json={"timezone": "Mars/Olympus_Mons"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "timezone"


async def test_update_profile_cannot_escalate_role_or_change_email(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, session: AsyncSession
) -> None:
    """Privilege escalation via mass assignment.

    `role` and `email` are absent from the update schema, and `extra="forbid"`
    turns an attempt into a 422 before any logic runs.
    """
    user = await make_user(with_profile=True)

    response = await client.patch(
        "/api/v1/auth/me",
        headers=auth_header(tokens.create(user_id=user.id)),
        json={"role": "admin", "email": "attacker@evil.test"},
    )

    assert response.status_code == 422
    assert_error(response.json(), "VALIDATION_ERROR")

    await session.refresh(await session.get(UserProfile, user.id))  # type: ignore[arg-type]
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    assert profile.role is UserRole.STUDENT


async def test_update_profile_trims_whitespace(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(with_profile=True)

    response = await client.patch(
        "/api/v1/auth/me",
        headers=auth_header(tokens.create(user_id=user.id)),
        json={"institution": "  JIPMER  "},
    )

    assert assert_success(response.json())["institution"] == "JIPMER"


# ── Authorization ────────────────────────────────────────────────────────────


async def test_admin_route_rejects_a_student(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(role="student")

    response = await client.get(
        "/api/v1/auth/admin/ping", headers=auth_header(tokens.create(user_id=user.id))
    )

    assert response.status_code == 403
    assert_error(response.json(), "FORBIDDEN")


async def test_admin_route_accepts_an_admin(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(role="admin")

    response = await client.get(
        "/api/v1/auth/admin/ping",
        headers=auth_header(tokens.create(user_id=user.id, role="admin")),
    )

    assert response.status_code == 200
    assert assert_success(response.json())["role"] == "admin"


async def test_admin_claim_in_token_does_not_grant_access(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """The critical authorization test.

    The token asserts `role: admin`, but the identity record says student. Because
    `require_role` reads the database rather than the claim, access is denied.
    This is what closes the stale-claim window after a demotion.
    """
    user = await make_user(role="student")

    response = await client.get(
        "/api/v1/auth/admin/ping",
        headers=auth_header(tokens.create(user_id=user.id, role="admin")),
    )

    assert response.status_code == 403
    assert_error(response.json(), "FORBIDDEN")


async def test_role_change_in_identity_service_propagates_to_the_profile(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, session: AsyncSession
) -> None:
    """Promoting a user in the identity service heals the local profile copy."""
    user = await make_user(role="student", with_profile=True)
    user.role = "admin"
    await session.flush()

    response = await client.get(
        "/api/v1/auth/admin/ping",
        headers=auth_header(tokens.create(user_id=user.id, role="admin")),
    )

    assert response.status_code == 200


# ── Session revocation ───────────────────────────────────────────────────────


async def test_revoking_a_session_blocks_further_requests(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    """Sign-out must make the outstanding access token unusable at once."""
    user = await make_user(with_profile=True)
    token = tokens.create(user_id=user.id, session_id="sess-live")

    revoke = await client.post("/api/v1/auth/sessions/revoke", headers=auth_header(token))
    assert revoke.status_code == 200
    assert assert_success(revoke.json())["revoked"] is True

    follow_up = await client.get("/api/v1/auth/me", headers=auth_header(token))
    assert follow_up.status_code == 401
    assert_error(follow_up.json(), "SESSION_REVOKED")


async def test_revoking_a_token_without_a_session_id_revokes_the_user(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, fake_redis: Any
) -> None:
    """With no session id the only safe revocation scope is the whole user."""
    user = await make_user(with_profile=True)
    token = tokens.create(user_id=user.id, session_id=None)

    response = await client.post("/api/v1/auth/sessions/revoke", headers=auth_header(token))

    assert response.status_code == 200
    assert await fake_redis.exists(f"{USER_REVOKED_PREFIX}{user.id}")


# ── Diagnostics ──────────────────────────────────────────────────────────────


async def test_session_diagnostics_exposes_no_secrets(
    client: AsyncClient, tokens: TokenFactory, make_user: Any
) -> None:
    user = await make_user(with_profile=True)
    token = tokens.create(user_id=user.id, session_id="sess-diag")

    response = await client.get("/api/v1/auth/session", headers=auth_header(token))

    data = assert_success(response.json())
    assert data["session_id"] == "sess-diag"
    assert data["role"] == "student"
    assert 0 < data["seconds_until_expiry"] <= 15 * 60
    # No credential material may appear anywhere in the payload.
    assert token not in response.text
    assert "email" not in data


# ── Audit trail ──────────────────────────────────────────────────────────────


async def test_denied_admin_access_is_audited(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, session: AsyncSession
) -> None:
    user = await make_user(role="student")

    await client.get("/api/v1/auth/admin/ping", headers=auth_header(tokens.create(user_id=user.id)))

    events = (
        await session.scalars(
            select(AuthAuditLog).where(
                AuthAuditLog.user_id == user.id,
                AuthAuditLog.event == AuthEvent.ACCESS_DENIED,
            )
        )
    ).all()
    assert len(events) == 1
    assert events[0].event_metadata == {"required_role": "admin", "actual_role": "student"}
    assert events[0].request_id


async def test_profile_update_is_audited_without_leaking_values(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, session: AsyncSession
) -> None:
    """The audit row records which fields changed, never the values."""
    user = await make_user(with_profile=True)

    await client.patch(
        "/api/v1/auth/me",
        headers=auth_header(tokens.create(user_id=user.id)),
        json={"institution": "AIIMS", "year_of_study": 4},
    )

    event = await session.scalar(
        select(AuthAuditLog).where(
            AuthAuditLog.user_id == user.id,
            AuthAuditLog.event == AuthEvent.PROFILE_UPDATE,
        )
    )
    assert event is not None
    fields = event.event_metadata["fields"]  # type: ignore[index]
    assert set(fields) == {"institution", "year_of_study", "onboarding_completed_at"}
    assert "AIIMS" not in str(event.event_metadata)


async def test_logout_is_audited(
    client: AsyncClient, tokens: TokenFactory, make_user: Any, session: AsyncSession
) -> None:
    user = await make_user(with_profile=True)

    await client.post(
        "/api/v1/auth/sessions/revoke",
        headers=auth_header(tokens.create(user_id=user.id, session_id="sess-out")),
    )

    event = await session.scalar(
        select(AuthAuditLog).where(
            AuthAuditLog.user_id == user.id, AuthAuditLog.event == AuthEvent.LOGOUT
        )
    )
    assert event is not None
    assert event.event_metadata == {"scope": "session"}
