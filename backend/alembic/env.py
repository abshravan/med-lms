"""Alembic environment.

Two things here are load-bearing:

1. The database URL comes from application settings, not `alembic.ini`, so no
   credentials live in version control.
2. `include_object` excludes every externally managed table. The Better Auth
   tables in the `auth` schema are migrated by the `better-auth` CLI; without
   this filter, `alembic revision --autogenerate` would confidently emit
   `DROP TABLE auth.user`. See docs/architecture.md §5.1.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

# Importing the model modules registers them on Base.metadata for autogenerate.
from app.models import auth as auth_models  # noqa: F401
from app.models import profile as profile_models  # noqa: F401
from app.models.base import EXTERNALLY_MANAGED, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Schemas owned by another migration tool. Never autogenerate against these.
EXTERNAL_SCHEMAS = frozenset({"auth"})


def include_object(
    obj: Any,
    _name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: Any,
) -> bool:
    """Filter objects out of autogenerate comparison."""
    if type_ == "table":
        if obj.schema in EXTERNAL_SCHEMAS:
            return False
        if obj.info.get(EXTERNALLY_MANAGED):
            return False
    if type_ in {"index", "column", "unique_constraint", "foreign_key_constraint"}:
        table = getattr(obj, "table", None)
        if table is not None and table.schema in EXTERNAL_SCHEMAS:
            return False
    return True


def _configure(connection: Connection | None = None, **extra: Any) -> None:
    """Shared configuration for both online and offline modes."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        # Detect column type changes and server-default changes, which Alembic
        # ignores by default and which are a common source of drift.
        compare_type=True,
        compare_server_default=True,
        # Wrap each migration in its own transaction so a failure rolls back
        # cleanly instead of leaving a half-applied schema.
        transaction_per_migration=True,
        version_table="alembic_version",
        **extra,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Used to produce a reviewable script for a production change window.
    """
    _configure(
        url=get_settings().sqlalchemy_dsn,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations on an established connection."""
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect and apply migrations."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_settings().sqlalchemy_dsn

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
