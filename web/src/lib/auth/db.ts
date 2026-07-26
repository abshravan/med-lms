/**
 * Postgres pool for Better Auth.
 *
 * **Why the raw `pg` driver and not an ORM.** Better Auth supports Prisma,
 * Drizzle, and Kysely adapters. Adding one would mean a second schema definition
 * and a second migration tool in a repository where Alembic already owns the
 * domain schema — two sources of truth for the same database, and a standing
 * invitation for drift. Better Auth's built-in Kysely adapter accepts a plain
 * `pg.Pool`, which gives us the same functionality with no extra schema layer.
 * If the web app ever needs to query domain tables directly it should call the
 * FastAPI API, not reach into Postgres.
 *
 * **Why `search_path`.** Better Auth issues unqualified table names. Setting the
 * connection's `search_path` to `auth` places every table it creates and queries
 * inside the `auth` schema, which is how the ownership split in
 * docs/architecture.md §5.1 is enforced at the connection level rather than by
 * remembering to prefix things.
 */

import { Pool } from "pg";

import { getServerEnv } from "@/lib/env";

/** Schema owned by Better Auth. */
export const AUTH_SCHEMA = "auth";

let pool: Pool | null = null;

/**
 * The process-wide connection pool.
 *
 * Cached on `globalThis` in development so Next.js hot reloads do not leak a new
 * pool on every recompile — a classic cause of "too many connections" locally.
 */
export function getAuthPool(): Pool {
  if (pool !== null) {
    return pool;
  }

  const globalCache = globalThis as typeof globalThis & {
    __medLmsAuthPool?: Pool;
  };

  if (globalCache.__medLmsAuthPool !== undefined) {
    pool = globalCache.__medLmsAuthPool;
    return pool;
  }

  const env = getServerEnv();

  pool = new Pool({
    connectionString: env.DATABASE_URL,
    // `public` stays on the path so shared extensions (pgcrypto) resolve.
    options: `-c search_path=${AUTH_SCHEMA},public`,
    // Sized for many small web replicas: each holds few connections so the
    // cluster total stays within Postgres' limit. Raise only alongside a pooler.
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
  });

  pool.on("error", (error) => {
    // An idle-client error must not take the process down.
    console.error("[auth-db] idle client error", error.message);
  });

  if (env.NODE_ENV !== "production") {
    globalCache.__medLmsAuthPool = pool;
  }

  return pool;
}
