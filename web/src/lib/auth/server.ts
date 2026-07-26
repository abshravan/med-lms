/**
 * Better Auth server configuration — the identity authority for the platform.
 *
 * This module is the single source of truth for authentication. It owns:
 *
 * - Credential handling (registration, sign-in, verification, password reset).
 * - Session issuance (cookies for web, bearer tokens for mobile).
 * - Minting the short-lived ES256 access tokens that FastAPI verifies, and
 *   publishing the matching public JWKS.
 *
 * It is also the config the `better-auth` CLI reads for `auth:migrate`, so the
 * tables it creates always match what runs at request time.
 *
 * See docs/architecture.md §3 for why identity lives here and not in FastAPI.
 */

import { betterAuth } from "better-auth";
import { admin, bearer, jwt } from "better-auth/plugins";
import { nextCookies } from "better-auth/next-js";

import { getAuthPool } from "@/lib/auth/db";
import { recordAuthEvent } from "@/lib/auth/audit";
import { getServerEnv, getTrustedOrigins } from "@/lib/env";
import { sendEmailSafely } from "@/lib/email";
import { passwordResetEmail, verificationEmail } from "@/lib/email/templates";

const env = getServerEnv();

/**
 * Access-token lifetime.
 *
 * 15 minutes is the deliberate midpoint of a real tradeoff: long enough that
 * clients are not constantly refreshing, short enough to bound the damage from a
 * leaked token. It must stay in sync with `ACCESS_TOKEN_TTL_SECONDS` in
 * backend/app/services/auth_service.py, which sizes the revocation deny-list.
 */
const ACCESS_TOKEN_EXPIRY = "15m";

export const auth = betterAuth({
  appName: "MedLMS",
  baseURL: env.BETTER_AUTH_URL,
  secret: env.BETTER_AUTH_SECRET,

  // Kysely adapter over the raw pg pool — see lib/auth/db.ts for the rationale.
  database: getAuthPool(),

  // Blocks cross-origin requests to the auth endpoints.
  trustedOrigins: getTrustedOrigins(),

  emailAndPassword: {
    enabled: true,

    // Sign-in is allowed before verification; content routes enforce it instead.
    // Blocking sign-in entirely means a user who mistypes their address has no
    // way back into the product to fix it.
    requireEmailVerification: false,

    // 12 is above the common 8-character minimum. Length is the property that
    // actually resists offline cracking, so it is preferred over composition
    // rules, which mostly push users toward `Password1!`.
    minPasswordLength: 12,
    maxPasswordLength: 128,

    sendResetPassword: async ({ user, url }) => {
      await sendEmailSafely(
        passwordResetEmail({ to: user.email, name: user.name ?? null, url }),
      );
      await recordAuthEvent({
        userId: user.id,
        event: "password_reset_request",
        outcome: "success",
      });
    },

    onPasswordReset: async ({ user }) => {
      // Every other session is already invalidated by Better Auth; this audits it
      // and lets support answer "when did my password change?".
      await recordAuthEvent({
        userId: user.id,
        event: "password_reset_complete",
        outcome: "success",
      });
    },
  },

  emailVerification: {
    sendOnSignUp: true,
    autoSignInAfterVerification: true,
    expiresIn: 60 * 60, // 1 hour

    sendVerificationEmail: async ({ user, url }) => {
      await sendEmailSafely(
        verificationEmail({ to: user.email, name: user.name ?? null, url }),
      );
    },

    afterEmailVerification: async (user) => {
      await recordAuthEvent({
        userId: user.id,
        event: "email_verify",
        outcome: "success",
      });
    },
  },

  session: {
    expiresIn: 60 * 60 * 24 * 7, // 7 days
    // Sliding expiry: an active user is not signed out mid-lesson, but the row is
    // only rewritten once a day rather than on every request.
    updateAge: 60 * 60 * 24,
    cookieCache: {
      // Avoids a database read on every request for session lookup. Kept short so
      // a revoked session is not honoured from cache for long.
      enabled: true,
      maxAge: 60 * 5,
    },
  },

  user: {
    additionalFields: {
      /**
       * Authoritative role. Mirrored into `public.user_profiles` by the API for
       * joins, but this column is the source of truth.
       */
      role: {
        type: "string",
        required: false,
        defaultValue: "student",
        // Critical: without this, a client could set its own role at sign-up.
        input: false,
      },
    },
  },

  advanced: {
    cookiePrefix: "medlms",
    useSecureCookies: env.NODE_ENV === "production",
    defaultCookieAttributes: {
      httpOnly: true,
      // Lax rather than Strict so following a verification link from an email
      // client still arrives authenticated.
      sameSite: "lax",
    },
  },

  databaseHooks: {
    user: {
      create: {
        after: async (user) => {
          await recordAuthEvent({
            userId: user.id,
            event: "register",
            outcome: "success",
          });
        },
      },
    },
    session: {
      create: {
        after: async (session) => {
          await recordAuthEvent({
            userId: session.userId,
            event: "login",
            outcome: "success",
            ipAddress: session.ipAddress ?? null,
            userAgent: session.userAgent ?? null,
          });
        },
      },
    },
  },

  plugins: [
    /**
     * Mints the access tokens FastAPI consumes and serves the public key set.
     *
     * ES256 rather than the default EdDSA: `PyJWT`'s JWK support for EC keys is
     * more broadly available than for OKP, and interop with the Python verifier
     * matters more here than the marginal benefits of Ed25519.
     */
    jwt({
      jwks: {
        keyPairConfig: { alg: "ES256" },
      },
      jwt: {
        issuer: env.BETTER_AUTH_URL,
        audience: env.AUTH_AUDIENCE,
        expirationTime: ACCESS_TOKEN_EXPIRY,

        /**
         * The claim set FastAPI reads.
         *
         * Deliberately minimal. A token is a bearer credential that may sit in
         * logs and proxies, so it carries only what authorization needs — no
         * profile data, no institution, nothing that would be a privacy problem
         * if the token were captured.
         *
         * `sid` is what makes per-session revocation possible on the API side.
         */
        definePayload: ({ user, session }) => ({
          email: user.email,
          emailVerified: user.emailVerified,
          role: typeof user.role === "string" ? user.role : "student",
          sid: session.id,
        }),
      },
    }),

    /**
     * Accepts `Authorization: Bearer <session-token>`, which is how the mobile
     * client authenticates — it has no cookie jar.
     */
    bearer(),

    /** Supplies the `role`, `banned`, and `banReason` columns the API reads. */
    admin({
      defaultRole: "student",
      adminRoles: ["admin"],
    }),

    /**
     * Must be last. Bridges Better Auth's cookie handling into the Next.js
     * server-action and route-handler cookie APIs.
     */
    nextCookies(),
  ],
});

export type Auth = typeof auth;
export type ServerSession = Awaited<ReturnType<typeof auth.api.getSession>>;
