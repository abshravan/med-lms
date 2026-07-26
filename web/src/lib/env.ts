/**
 * Validated environment access.
 *
 * Rule 12/15: environment variables are used correctly and secrets are never
 * hardcoded. Both are enforced here rather than by convention:
 *
 * - `serverEnv` is validated lazily and throws a legible error listing every
 *   missing variable, so a misconfigured deploy fails at boot instead of
 *   producing a confusing 500 on the first sign-in attempt.
 * - `clientEnv` is validated eagerly at module load. Only `NEXT_PUBLIC_*` names
 *   appear there, which is what stops a secret from being inlined into the
 *   browser bundle: importing a server-only name from a client component is a
 *   type error, not a silent leak.
 */

import { z } from "zod";

const serverSchema = z.object({
  NODE_ENV: z
    .enum(["development", "test", "production"])
    .default("development"),

  DATABASE_URL: z
    .string()
    .min(1, "DATABASE_URL is required")
    .refine((value) => value.startsWith("postgres"), {
      message: "DATABASE_URL must be a PostgreSQL connection string",
    }),

  /**
   * Signs session cookies. Must be high-entropy and identical across every web
   * replica, or users will be logged out at random as requests land on different
   * instances. Generate with `openssl rand -base64 32`.
   */
  BETTER_AUTH_SECRET: z
    .string()
    .min(32, "BETTER_AUTH_SECRET must be at least 32 characters"),

  /** Public base URL of this app. Becomes the JWT `iss` claim. */
  BETTER_AUTH_URL: z.string().url("BETTER_AUTH_URL must be an absolute URL"),

  /** JWT `aud` claim. Must match AUTH_AUDIENCE on the FastAPI side exactly. */
  AUTH_AUDIENCE: z.string().min(1).default("med-lms-api"),

  /** Base URL the *server* uses to reach the domain API (container network). */
  API_INTERNAL_URL: z.string().url().default("http://localhost:8000"),

  EMAIL_FROM: z.string().email().default("no-reply@medlms.local"),
  /** Absent in development: emails are then logged to the console instead. */
  RESEND_API_KEY: z.string().optional(),

  /** Trusted origins for Better Auth's CSRF origin check. Comma-separated. */
  TRUSTED_ORIGINS: z.string().optional(),
});

const clientSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url().default("http://localhost:8000"),
  NEXT_PUBLIC_APP_URL: z.string().url().default("http://localhost:3000"),
});

export type ServerEnv = z.infer<typeof serverSchema>;
export type ClientEnv = z.infer<typeof clientSchema>;

function formatIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) => `  - ${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("\n");
}

let cachedServerEnv: ServerEnv | null = null;

/**
 * Placeholders used **only** while `next build` collects page data.
 *
 * The build evaluates every route module, including the ones that construct the
 * Better Auth instance. Without this, compiling the app would require the real
 * production database URL and signing secret — so CI would need production
 * credentials just to typecheck and bundle.
 *
 * The alternative — baking dummy values into the image as `ENV` — is worse: if an
 * operator then forgot to supply `BETTER_AUTH_SECRET` at runtime, the container
 * would happily boot and sign every session cookie with a public, well-known
 * secret. That is a silent, total authentication bypass.
 *
 * This gate closes the moment the build ends. `NEXT_PHASE` is set by the Next.js
 * CLI during `next build` and is never present in a running server, so at runtime
 * validation is always strict and a missing secret still fails the boot loudly.
 */
const BUILD_PHASE_PLACEHOLDERS: Record<string, string> = {
  DATABASE_URL: "postgresql://build:build@localhost:5432/build",
  BETTER_AUTH_SECRET: "build-phase-placeholder-not-a-real-secret-32",
  BETTER_AUTH_URL: "http://localhost:3000",
};

function isBuildPhase(): boolean {
  return process.env.NEXT_PHASE === "phase-production-build";
}

/**
 * Validated server-side environment.
 *
 * Lazy so that importing a module which merely *mentions* `serverEnv` does not
 * crash a client build. Cached so validation runs once per process.
 *
 * @throws If any required variable is missing or malformed at runtime.
 */
export function getServerEnv(): ServerEnv {
  if (cachedServerEnv !== null) {
    return cachedServerEnv;
  }

  const source = isBuildPhase()
    ? { ...BUILD_PHASE_PLACEHOLDERS, ...process.env }
    : process.env;

  const parsed = serverSchema.safeParse(source);
  if (!parsed.success) {
    throw new Error(
      `Invalid server environment configuration:\n${formatIssues(parsed.error)}\n\n` +
        `See web/.env.example for the full contract.`,
    );
  }

  cachedServerEnv = parsed.data;
  return cachedServerEnv;
}

/**
 * Validated public environment, safe to read from client components.
 *
 * Values are referenced explicitly rather than by spreading `process.env`,
 * because Next.js only inlines statically-analysable member accesses.
 */
export const clientEnv: ClientEnv = (() => {
  const parsed = clientSchema.safeParse({
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL,
  });

  if (!parsed.success) {
    throw new Error(
      `Invalid public environment configuration:\n${formatIssues(parsed.error)}`,
    );
  }

  return parsed.data;
})();

/** Trusted origins for the CSRF origin check, always including the app's own URL. */
export function getTrustedOrigins(): string[] {
  const env = getServerEnv();
  const extra = (env.TRUSTED_ORIGINS ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter((origin) => origin.length > 0);

  return Array.from(new Set([env.BETTER_AUTH_URL, ...extra]));
}
