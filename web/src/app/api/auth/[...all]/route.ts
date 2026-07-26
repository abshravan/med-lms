/**
 * Better Auth HTTP handler.
 *
 * Mounts the whole identity surface under `/api/auth/*` on the web origin:
 *
 *   POST /api/auth/sign-up/email
 *   POST /api/auth/sign-in/email
 *   POST /api/auth/sign-out
 *   POST /api/auth/forget-password
 *   POST /api/auth/reset-password
 *   GET  /api/auth/verify-email
 *   GET  /api/auth/get-session
 *   GET  /api/auth/token            → short-lived ES256 access token for FastAPI
 *   GET  /api/auth/jwks             → public keys FastAPI verifies against
 *
 * These are Better Auth's own routes and are versioned by the library, which is
 * why they sit outside the `/api/v1` domain namespace.
 */

import { toNextJsHandler } from "better-auth/next-js";

import { auth } from "@/lib/auth/server";

export const { GET, POST } = toNextJsHandler(auth.handler);

/**
 * Node runtime, not Edge: the `pg` driver and the Node crypto primitives used for
 * key generation are unavailable on the Edge runtime.
 */
export const runtime = "nodejs";

/** Auth responses are per-user and must never be cached by Next or a CDN. */
export const dynamic = "force-dynamic";
