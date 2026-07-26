/**
 * Create the `auth` schema before Better Auth migrates into it.
 *
 * The Better Auth CLI creates *tables*, not schemas, and the pool sets
 * `search_path=auth`, so without this the first migration fails with
 * "no schema has been selected to create in".
 *
 * Docker Compose handles this via an initdb script for fresh volumes; this exists
 * for every other case — a managed Postgres instance, an existing volume, or CI.
 * Idempotent, so running it repeatedly is harmless.
 *
 * Run with: pnpm auth:bootstrap
 */

import { Pool } from "pg";

async function main(): Promise<void> {
  const connectionString = process.env.DATABASE_URL;

  if (connectionString === undefined || connectionString.length === 0) {
    console.error("error: DATABASE_URL is not set.");
    process.exit(1);
  }

  // A dedicated pool with no `search_path` override — the schema it is about to
  // create does not exist yet.
  const pool = new Pool({ connectionString, max: 1 });

  try {
    await pool.query("CREATE SCHEMA IF NOT EXISTS auth");
    // Needed by the audit table's server-side default for `id`.
    await pool.query("CREATE EXTENSION IF NOT EXISTS pgcrypto");
    console.info("[auth-bootstrap] schema 'auth' and extension 'pgcrypto' are ready");
  } catch (error) {
    console.error(
      "[auth-bootstrap] failed:",
      error instanceof Error ? error.message : String(error),
    );
    process.exit(1);
  } finally {
    await pool.end();
  }
}

void main();
