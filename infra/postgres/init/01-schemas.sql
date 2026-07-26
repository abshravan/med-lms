-- Database bootstrap, run once by the Postgres image on first initialisation.
--
-- The `auth` schema must exist before the Better Auth CLI migrates into it, and
-- before Alembic adds the foreign key from public.user_profiles to auth.user.
-- Creating it here keeps both migration tools free of bootstrap responsibility.
--
-- Ownership: docs/architecture.md §5.1
--   auth   → migrated by the `better-auth` CLI (Node)
--   public → migrated by Alembic (Python)

CREATE SCHEMA IF NOT EXISTS auth;

-- gen_random_uuid(), used as a server-side default for audit ids.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
