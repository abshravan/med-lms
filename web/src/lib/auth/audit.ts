/**
 * Audit writes from the identity service.
 *
 * Registration, sign-in, verification, and password reset all happen inside
 * Better Auth, so the identity service is the only place that can observe them.
 * They are written to `public.auth_audit_log` — the same table the API writes to
 * — giving one chronological trail per user instead of two half-stories.
 *
 * Ownership: Alembic owns the table's *schema*; both services are permitted
 * *writers*. That split is recorded in docs/architecture.md §5.1.
 *
 * Failures are swallowed by design: an audit write must never be able to fail a
 * registration or a sign-in. Losing an audit row is a monitoring problem; losing
 * a sign-up is a revenue problem.
 */

import { getAuthPool } from "@/lib/auth/db";

/** Mirrors the `auth_event` enum in the database. */
export type AuthEventName =
  | "register"
  | "login"
  | "logout"
  | "email_verify"
  | "password_reset_request"
  | "password_reset_complete"
  | "token_rejected"
  | "access_denied"
  | "profile_update";

export type AuthOutcome = "success" | "failure";

export interface AuthEventInput {
  event: AuthEventName;
  outcome: AuthOutcome;
  userId?: string | null;
  ipAddress?: string | null;
  userAgent?: string | null;
  requestId?: string | null;
  /** Non-sensitive context only. Never tokens, passwords, or email addresses. */
  metadata?: Record<string, string | number | boolean> | null;
}

/**
 * `public` is qualified explicitly because the pool's `search_path` puts `auth`
 * first — without the prefix this would look for `auth.auth_audit_log`.
 */
const INSERT_EVENT = `
  INSERT INTO public.auth_audit_log
    (id, user_id, event, outcome, ip_address, user_agent, request_id, metadata)
  VALUES
    (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7)
`;

function truncate(value: string | null | undefined, max: number): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return value.length > max ? value.slice(0, max) : value;
}

/**
 * Append an audit row. Never throws.
 *
 * @returns Whether the row was written, for callers that want to assert on it in
 *          tests. Production callers can ignore it.
 */
export async function recordAuthEvent(input: AuthEventInput): Promise<boolean> {
  try {
    await getAuthPool().query(INSERT_EVENT, [
      input.userId ?? null,
      input.event,
      input.outcome,
      // The column is INET; an unparseable value would abort the statement, so
      // anything that is not obviously an address is stored as NULL.
      normaliseIpAddress(input.ipAddress),
      truncate(input.userAgent, 512),
      truncate(input.requestId, 64),
      input.metadata !== undefined && input.metadata !== null
        ? JSON.stringify(input.metadata)
        : null,
    ]);
    return true;
  } catch (error) {
    console.error(
      `[audit] failed to record ${input.event}`,
      error instanceof Error ? error.message : String(error),
    );
    return false;
  }
}

/** Accept only values plausible as an IPv4/IPv6 literal; otherwise NULL. */
function normaliseIpAddress(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value.length === 0) {
    return null;
  }
  const candidate = value.trim();
  const looksLikeAddress = /^[0-9a-fA-F:.]+$/.test(candidate) && candidate.length <= 45;
  return looksLikeAddress ? candidate : null;
}
