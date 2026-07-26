#!/usr/bin/env bash
#
# Run all database migrations in the required order.
#
# Ordering is not optional. Two tools own two schemas (docs/architecture.md §5.1):
#
#   1. better-auth CLI  → the `auth` schema (user, session, account, verification, jwks)
#   2. Alembic          → the `public` schema, including a foreign key to auth.user
#
# Running Alembic first fails with a clear error rather than a half-applied schema,
# but the right answer is simply to use this script.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL is not set." >&2
  echo "       Export it, or source your .env before running this script." >&2
  exit 1
fi

echo "==> 1/3  Ensuring the 'auth' schema exists"
# Idempotent, and needed before Better Auth can create tables inside it. Uses the
# web workspace's pg client so no psql binary is required on the host.
(cd "$REPO_ROOT/web" && pnpm --silent auth:bootstrap)

echo "==> 2/3  Migrating the identity schema (better-auth → auth)"
(cd "$REPO_ROOT/web" && pnpm --silent auth:migrate)

echo "==> 3/3  Migrating the application schema (alembic → public)"
(cd "$REPO_ROOT/backend" && python -m alembic upgrade head)

echo "==> Migrations complete."
