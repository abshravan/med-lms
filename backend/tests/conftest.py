"""Shared test fixtures.

Design choices worth stating:

* **Migrations are applied by running Alembic**, not `metadata.create_all`. That
  means the tests exercise the same DDL that production will run, so a broken
  migration fails the suite instead of reaching a deploy.
* **Tokens are signed with a real ES256 keypair** generated per session, and the
  JWKS endpoint is served through `respx`. The verification path under test is
  the production one — fetch, cache, select key, verify — with nothing stubbed
  out inside `app.core.security`.
* **Redis is faked** (`fakeredis`) because the deny-list semantics we care about
  are `SET`/`EXISTS` with a TTL, which fakeredis implements faithfully.
* Each test runs in a transaction that is rolled back, so tests are order
  independent and leave no rows behind.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Settings are read once and cached, so the environment must be complete before
# anything under `app.` is imported.
TEST_DATABASE_URL = os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql://medlms@127.0.0.1:55432/med_lms_test",
)
TEST_ISSUER = "http://localhost:3000"
TEST_AUDIENCE = "med-lms-api"
TEST_JWKS_URL = "http://web:3000/api/auth/jwks"

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "DATABASE_URL": TEST_DATABASE_URL,
        "REDIS_URL": "redis://localhost:6379/15",
        "AUTH_JWKS_URL": TEST_JWKS_URL,
        "AUTH_ISSUER": TEST_ISSUER,
        "AUTH_AUDIENCE": TEST_AUDIENCE,
    }
)

import fakeredis.aioredis  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient, Response  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core import redis as redis_module  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import get_db_session  # noqa: E402
from app.core.security import reset_jwks_cache  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.auth import AuthUser  # noqa: E402
from app.models.course import (  # noqa: E402
    ContentStatus,
    Course,
    Difficulty,
    Lesson,
    LessonContentType,
    Module,
)
from app.models.profile import UserProfile, UserRole  # noqa: E402

ASYNC_DSN = get_settings().sqlalchemy_dsn


# ── Database lifecycle ───────────────────────────────────────────────────────


def _run_alembic(*args: str) -> None:
    """Invoke the Alembic CLI as a subprocess.

    A subprocess rather than the programmatic API because `alembic/env.py` calls
    `asyncio.run`, which cannot execute inside an already-running event loop.
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


AUTH_SCHEMA_SQL = BACKEND_ROOT.parent / "infra" / "postgres" / "reference" / "auth-schema.sql"


async def _reset_database() -> None:
    """Drop everything, then recreate the identity schema Better Auth owns.

    The identity DDL is applied from `infra/postgres/reference/auth-schema.sql`,
    which is a `pg_dump` of what the `better-auth` CLI actually produces — not a
    hand-written approximation. That matters: the ORM mapping in
    `app/models/auth.py` declares `String(255)` where Better Auth uses `text`, and
    nullable where it is `NOT NULL`. Testing against the real DDL is what proves
    the read-only mapping is genuinely compatible with the production schema
    instead of merely compatible with itself.
    """
    engine = create_async_engine(ASYNC_DSN, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await connection.execute(text("CREATE SCHEMA auth"))
        for statement in _split_sql_statements(AUTH_SCHEMA_SQL.read_text()):
            await connection.execute(text(statement))
    await engine.dispose()


def _split_sql_statements(sql: str) -> list[str]:
    """Split a plain SQL script into individual statements.

    Necessary because asyncpg refuses multiple commands in one prepared statement.
    The reference dump contains only plain DDL — no functions, triggers, or
    dollar-quoted bodies — so splitting on `;` is sufficient here. If the dump ever
    grows a `$$`-quoted block this will need a real parser.
    """
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> Iterator[None]:
    """Prepare the schema once per test session."""
    import asyncio

    try:
        asyncio.run(_reset_database())
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres is not reachable at {TEST_DATABASE_URL}: {exc}")
    _run_alembic("upgrade", "head")
    yield


@pytest.fixture
async def engine() -> AsyncIterator[Any]:
    """A per-test engine.

    Function-scoped with `NullPool` so no connection is ever shared across event
    loops, which is the usual cause of mysterious hangs in async test suites.
    """
    test_engine = create_async_engine(ASYNC_DSN, poolclass=NullPool)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def session(engine: Any) -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is always rolled back.

    The service layer calls `commit()`. Binding the session to an outer
    transaction turns those commits into savepoint releases, so application code
    behaves normally while the test still leaves the database untouched.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as test_session:
            yield test_session
        await transaction.rollback()


# ── Redis ────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fake_redis() -> Iterator[fakeredis.aioredis.FakeRedis]:
    """Replace the Redis client with an in-memory fake for every test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_module.set_redis_client(client)
    yield client
    redis_module.set_redis_client(None)


# ── Signing keys and tokens ──────────────────────────────────────────────────


class TokenFactory:
    """Mints ES256 tokens for tests, mirroring what Better Auth issues."""

    def __init__(self, key_id: str = "test-key-1") -> None:
        self.key_id = key_id
        self._private_key = ec.generate_private_key(ec.SECP256R1())

    @property
    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        """The public key set, in the shape Better Auth publishes."""
        public_jwk = jwt.algorithms.ECAlgorithm.to_jwk(self._private_key.public_key(), as_dict=True)
        public_jwk.update({"kid": self.key_id, "use": "sig", "alg": "ES256"})
        return {"keys": [public_jwk]}

    def create(
        self,
        *,
        user_id: str,
        session_id: str | None = "sess-1",
        role: str = "student",
        email: str | None = "student@med.test",
        email_verified: bool = True,
        issuer: str = TEST_ISSUER,
        audience: str = TEST_AUDIENCE,
        expires_in: timedelta = timedelta(minutes=15),
        key_id: str | None = None,
        algorithm: str = "ES256",
    ) -> str:
        """Create a signed access token. Every field is overridable so negative
        cases (wrong audience, expired, unknown key) are expressible."""
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": user_id,
            "iss": issuer,
            "aud": audience,
            "iat": int(now.timestamp()),
            "exp": int((now + expires_in).timestamp()),
            "email": email,
            "emailVerified": email_verified,
            "role": role,
        }
        if session_id is not None:
            payload["sid"] = session_id
        return jwt.encode(
            payload,
            self._private_key,  # type: ignore[arg-type]
            algorithm=algorithm,
            headers={"kid": key_id or self.key_id},
        )


@pytest.fixture
def tokens() -> Iterator[TokenFactory]:
    """A token factory with a fresh keypair, and a clean JWKS cache."""
    reset_jwks_cache()
    factory = TokenFactory()
    yield factory
    reset_jwks_cache()


@pytest.fixture
def jwks_endpoint(tokens: TokenFactory) -> Iterator[respx.MockRouter]:
    """Serve the token factory's public keys at the configured JWKS URL."""
    with respx.mock(assert_all_called=False) as router:
        router.get(TEST_JWKS_URL).mock(return_value=Response(200, json=tokens.jwks))
        yield router


# ── Application ──────────────────────────────────────────────────────────────


@pytest.fixture
def app(session: AsyncSession) -> Iterator[FastAPI]:
    """The application, with the database dependency bound to the test session."""
    application = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    application.dependency_overrides[get_db_session] = override_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI, jwks_endpoint: respx.MockRouter) -> AsyncIterator[AsyncClient]:
    """An HTTP client speaking to the app in-process.

    `respx` is active, so outbound JWKS fetches are intercepted while requests to
    the ASGI app itself pass through.
    """
    jwks_endpoint.route(name="asgi").pass_through()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://api.test") as http_client:
        yield http_client


# ── Data builders ────────────────────────────────────────────────────────────


@pytest.fixture
def make_user(session: AsyncSession):  # type: ignore[no-untyped-def]
    """Factory inserting an identity row, optionally with a profile."""

    async def _make(
        *,
        user_id: str | None = None,
        email: str | None = None,
        email_verified: bool = True,
        name: str | None = "Ada Lovelace",
        role: str | None = "student",
        banned: bool | None = False,
        with_profile: bool = False,
        profile_role: UserRole = UserRole.STUDENT,
    ) -> AuthUser:
        resolved_id = user_id or f"user_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        user = AuthUser(
            id=resolved_id,
            email=email or f"{resolved_id}@med.test",
            email_verified=email_verified,
            name=name,
            image=None,
            role=role,
            banned=banned,
            ban_reason=None,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        if with_profile:
            session.add(UserProfile(user_id=resolved_id, role=profile_role, display_name=name))
        await session.flush()
        return user

    return _make


@pytest.fixture
def make_course(session: AsyncSession):  # type: ignore[no-untyped-def]
    """Factory building a course with optional modules and lessons.

    Builds the object graph directly rather than through the API, so catalogue
    read tests are not coupled to the authoring endpoints working.
    """

    async def _make(
        *,
        title: str = "Cardiology Basics",
        slug: str | None = None,
        status: ContentStatus = ContentStatus.PUBLISHED,
        specialty: str | None = "Cardiology",
        difficulty: Difficulty = Difficulty.FOUNDATION,
        published_at: datetime | None = None,
        modules: int = 1,
        lessons_per_module: int = 2,
        lesson_status: ContentStatus | None = None,
        lesson_duration: int | None = 600,
        created_by: str | None = None,
    ) -> Course:
        resolved_slug = slug or f"course-{uuid.uuid4().hex[:10]}"
        # The check constraint requires a timestamp whenever status is published.
        resolved_published_at = published_at
        if status is ContentStatus.PUBLISHED and resolved_published_at is None:
            resolved_published_at = datetime.now(UTC)

        course = Course(
            slug=resolved_slug,
            title=title,
            subtitle=None,
            description=None,
            specialty=specialty,
            difficulty=difficulty,
            status=status,
            published_at=resolved_published_at,
            created_by=created_by,
        )
        session.add(course)
        await session.flush()

        effective_lesson_status = (
            lesson_status
            if lesson_status is not None
            else (
                ContentStatus.PUBLISHED
                if status is ContentStatus.PUBLISHED
                else ContentStatus.DRAFT
            )
        )

        for module_index in range(modules):
            module = Module(
                course_id=course.id,
                title=f"Module {module_index + 1}",
                summary=None,
                position=module_index,
            )
            session.add(module)
            await session.flush()

            for lesson_index in range(lessons_per_module):
                session.add(
                    Lesson(
                        module_id=module.id,
                        course_id=course.id,
                        slug=f"{resolved_slug}-m{module_index}-l{lesson_index}",
                        title=f"Lesson {lesson_index + 1}",
                        summary=None,
                        content_type=LessonContentType.VIDEO,
                        duration_seconds=lesson_duration,
                        is_free_preview=False,
                        status=effective_lesson_status,
                        position=lesson_index,
                        published_at=(
                            datetime.now(UTC)
                            if effective_lesson_status is ContentStatus.PUBLISHED
                            else None
                        ),
                    )
                )

        await session.flush()
        return course

    return _make
