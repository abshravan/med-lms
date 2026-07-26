/**
 * Auth feature types.
 *
 * Mirrors `backend/app/schemas/auth.py`. Snake_case field names are preserved
 * deliberately: renaming at the boundary means every field exists under two names
 * across the codebase, and a mismatch then fails at runtime instead of at compile
 * time. Matching the wire format keeps the contract checkable.
 */

export type UserRole = "student" | "admin";

/** Response of `GET /api/v1/auth/me`. */
export interface UserProfile {
  user_id: string;
  email: string;
  email_verified: boolean;
  display_name: string | null;
  role: UserRole;
  institution: string | null;
  year_of_study: number | null;
  specialization: string | null;
  timezone: string;
  locale: string;
  onboarding_completed: boolean;
  last_active_at: string | null;
  created_at: string;
}

/** Response of `GET /api/v1/auth/session`. */
export interface AuthDiagnostics {
  user_id: string;
  role: string;
  session_id: string | null;
  email_verified: boolean;
  expires_at: string;
  seconds_until_expiry: number;
}

/** Response of `POST /api/v1/auth/sessions/revoke`. */
export interface RevocationResult {
  revoked: boolean;
  expires_in_seconds: number;
}
