/**
 * Better Auth browser client.
 *
 * Note the absence of `jwtClient()`. Its only client-side action is fetching the
 * JWKS, which the browser has no use for — signature verification happens in
 * FastAPI, and the access token is retrieved by a direct `fetch` to
 * `/api/auth/token` in lib/api/client.ts. Including the plugin would add a
 * client-side action nothing calls, and in better-auth 1.6.x its declared types
 * conflict with the client's fetch types, so leaving it out is both simpler and
 * type-clean.
 */

"use client";

import { adminClient } from "better-auth/client/plugins";
import { createAuthClient } from "better-auth/react";

import { clientEnv } from "@/lib/env";

export const authClient = createAuthClient({
  baseURL: clientEnv.NEXT_PUBLIC_APP_URL,
  plugins: [adminClient()],
});

export const {
  signIn,
  signUp,
  signOut,
  useSession,
  /** Sends the reset email. Named `forgetPassword` before better-auth 1.3. */
  requestPasswordReset,
  resetPassword,
  sendVerificationEmail,
} = authClient;

/** The session shape as the client sees it. */
export type ClientSession = ReturnType<typeof authClient.useSession>;
