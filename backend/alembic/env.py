"""Alembic environment.

Two things here are load-bearing:

1. The database URL comes from application settings, not `alembic.ini`, so no
   credentials live in version control.
2. `include_object` excludes every object autogenerate must not manage:

   * The Better Auth tables in the `auth` schema, migrated by the `better-auth`
     CLI. Without the filter, `--autogenerate` would confidently emit
     `DROP TABLE auth.user`. See docs/architecture.md §5.1.
   * Partition child tables, which exist in Postgres but never in the model
     metadata. Without the filter, every autogenerate run would emit a
     `DROP TABLE` for each monthly `auth_audit_log_*` partition — and applying
     that would destroy the audit history the partitioning exists to preserve.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

# Importing the model modules registers them on Base.metadata for autogenerate.
from app.models import auth as auth_models  # noqa: F401
from app.models import course as course_models  # noqa: F401
from app.models import media as media_models  # noqa: F401
from app.models import profile as profile_models  # noqa: F401
from app.models.base import EXTERNALLY_MANAGED, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Schemas owned by another migration tool. Never autogenerate against these.
EXTERNAL_SCHEMAS = frozenset({"auth"})

# Names of partition child tables discovered in the target database.
#
# Partitions exist in Postgres but never in `Base.metadata` — only the parent is
# declared. Without this, every `--autogenerate` run emits `DROP TABLE` for each
# one, and applying that migration would silently destroy the audit history it
# was supposed to be preserving.
_partition_tables: set[str] = set()

PARTITION_QUERY = """
SELECT child.relname
FROM pg_inherits
JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
JOIN pg_class child  ON child.oid  = pg_inherits.inhrelid
WHERE parent.relkind = 'p'
"""


def _load_partition_tables(connection: Connection) -> None:
    """Record every partition child table so autogenerate ignores them."""
    _partition_tables.clear()
    _partition_tables.update(row[0] for row in connection.execute(sa.text(PARTITION_QUERY)))


def include_object(
    obj: Any,
    _name: str | None,
    type_: str,
    _reflected: bool,  # noqa: N803 - positional contract fixed by Alembic
    _compare_to: Any,
) -> bool:
    """Filter objects out of autogenerate comparison."""
    if type_ == "table":
        if obj.schema in EXTERNAL_SCHEMAS:
            return False
        if obj.info.get(EXTERNALLY_MANAGED):
            return False
        # Partition children are managed by the migration that creates the parent,
        # never by autogenerate — see `_load_partition_tables`.
        if _reflected and obj.name in _partition_tables:
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
    _load_partition_tables(connection)
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
        # This commit is load-bearing, not defensive.
        #
        # `_load_partition_tables` issues a SELECT before Alembic takes control of
        # the connection, which opens an implicit transaction. SQLAlchemy rolls
        # that transaction back when the connection closes — silently discarding
        # every DDL statement the migration just issued, while Alembic still
        # reports "Running upgrade …" and exits 0. A migration that claims success
        # and does nothing is far worse than one that fails loudly, so the commit
        # is explicit here rather than left to Alembic's internal bookkeeping.
        await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
