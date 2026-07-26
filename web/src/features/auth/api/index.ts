/**
 * Domain-API calls for the auth feature.
 *
 * Only the FastAPI side lives here. Credential operations (sign-in, sign-up,
 * reset) go through `authClient` because Better Auth owns them — mixing the two
 * in one module is what makes people forget which service owns what.
 */

import { api } from "@/lib/api/client";
import type { ProfileUpdateInput } from "@/features/auth/schemas";
import type { AuthDiagnostics, RevocationResult, UserProfile } from "@/features/auth/types";

/** Paths are centralised so a version bump is one edit, not a grep. */
export const authApiPaths = {
  me: "/api/v1/auth/me",
  session: "/api/v1/auth/session",
  revokeSession: "/api/v1/auth/sessions/revoke",
} as const;

/** Fetch the authenticated user's profile. */
export function fetchProfile(signal?: AbortSignal): Promise<UserProfile> {
  return api.get<UserProfile>(authApiPaths.me, signal !== undefined ? { signal } : {});
}

/** Apply a partial profile update. */
export function updateProfile(input: ProfileUpdateInput): Promise<UserProfile> {
  return api.patch<UserProfile>(authApiPaths.me, input);
}

/** Read non-sensitive diagnostics about the current access token. */
export function fetchSessionDiagnostics(): Promise<AuthDiagnostics> {
  return api.get<AuthDiagnostics>(authApiPaths.session);
}

/**
 * Ask the API to deny-list the current session's access token.
 *
 * Called during sign-out, *before* Better Auth destroys the cookie session, so
 * the already-issued JWT stops being accepted immediately rather than remaining
 * valid for the rest of its 15-minute life.
 */
export function revokeCurrentSession(): Promise<RevocationResult> {
  return api.post<RevocationResult>(authApiPaths.revokeSession);
}
