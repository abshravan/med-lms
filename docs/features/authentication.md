# Feature 1 — Authentication

Status: **complete**. Backend, frontend, validation, error handling, loading
states, tests, and documentation all shipped.

---

## 1. What was built

| Capability | Where |
| --- | --- |
| Register with email + password | Better Auth (`/api/auth/sign-up/email`) |
| Email verification (send, resend, consume) | Better Auth + `/verify-email` |
| Sign in / sign out | Better Auth + `useSignOut` |
| Password reset (request, consume) | Better Auth + `/forgot-password`, `/reset-password` |
| Short-lived access tokens for the domain API | Better Auth `jwt` plugin |
| Offline token verification | `backend/app/core/security.py` |
| Session revocation | Redis deny-list + `POST /auth/sessions/revoke` |
| Role-based authorization | `require_role()` — reads the **database** |
| Profile read/update | `GET`/`PATCH /api/v1/auth/me` |
| Audit trail | `public.auth_audit_log`, written by both services |

Out of scope by design: OAuth providers, 2FA, magic links, organisations, admin
user management. All are Better Auth plugins that can be enabled later without
changing this architecture.

---

## 2. The central decision

The stack specifies **Better Auth**, a TypeScript library that cannot run inside
FastAPI. Three options were compared in
[architecture.md §3](../architecture.md#3-identity-the-one-genuinely-contentious-decision):

**Chosen:** Better Auth in Next.js is the identity authority and mints
short-lived ES256 JWTs; FastAPI verifies them offline against a cached JWKS.

Why this and not the alternatives:

- **Rebuilding auth in FastAPI** means re-implementing password hashing, email
  verification, single-use reset semantics, OAuth callbacks, and replay
  protection. Weeks of work, and every item is a place to introduce a CVE.
- **A hosted IdP** (Clerk/Auth0) costs real money at 100k MAU and introduces a
  third-party data-residency question for a medical-education product.
- Offline verification means **zero network calls per request** — the property
  that lets the API scale horizontally without loading the identity service.

Asymmetric ES256 rather than HS256 is the other load-bearing choice: with HS256
the signing secret would have to be shared, so every service that can *verify*
could also *forge*. FastAPI holds public keys only.

---

## 3. Security properties, and how each is verified

| Property | Mechanism | Test |
| --- | --- | --- |
| No `alg: none` bypass | Algorithms pinned to `("ES256",)`; the verifier decides, never the token | `test_unsigned_token_is_rejected` |
| No HS256 confusion | Same pin | `test_hs256_token_is_rejected` |
| No foreign-key forgery | Signature checked against published JWKS, even when `kid` is spoofed | `test_token_signed_by_a_foreign_key_is_rejected` |
| Not reusable on another API | `aud` verified | `test_token_for_another_audience_is_rejected` |
| Not issued by another provider | `iss` verified | `test_token_from_unknown_issuer_is_rejected` |
| Expiry enforced | `exp` + 10s skew leeway | `test_expired_token_is_rejected` |
| Sign-out is immediate | Redis deny-list, checked per request | `test_revoking_a_session_blocks_further_requests` |
| Ban is immediate | Ban check + user-wide revocation | `test_me_rejects_a_banned_account_and_revokes_its_tokens` |
| **Stale admin claim cannot escalate** | Role read from Postgres, not the claim | `test_admin_claim_in_token_does_not_grant_access` |
| No role escalation via profile PATCH | `role`/`email` absent from schema + `extra="forbid"` | `test_update_profile_cannot_escalate_role_or_change_email` |
| No role escalation at sign-up | `input: false` on the Better Auth field | `RegisterForm > never sends a role…` |
| No account enumeration | Identical responses for existing/absent emails | `LoginForm`, `RegisterForm` message tests |
| No open redirect | `next` param validated in middleware **and** at the point of use | `safeRedirectTarget`, `safeNext` |
| No internals leaked on error | Generic 500 + request id only | `test_unhandled_errors_do_not_leak_internals` |
| No log injection | `X-Request-ID` shape-checked | `test_malicious_request_id_is_replaced` |
| No PII in logs | structlog redaction processor | `core/logging.py` `REDACTED_KEYS` |
| Token not stealable via XSS | Access token in memory only; session cookie `httpOnly` | `lib/api/client.ts` |

### Explicit non-guarantees

1. **Middleware is not a security boundary.** It runs on the Edge runtime and can
   only see that a session cookie *exists*. Real enforcement is
   `app/(app)/layout.tsx` (validates the session server-side) and FastAPI's
   signature verification. This is stated at the top of `src/middleware.ts`
   because treating middleware as the gate is a classic mistake.

2. **The revocation deny-list fails open.** If Redis is unreachable, a valid
   unexpired signature is still accepted. Failing closed would turn a Redis blip
   into a total API outage. Residual exposure is bounded at 15 minutes for an
   already-authenticated user. Revisit per-route for exam-integrity features.

---

## 4. Verified end-to-end

Run against real PostgreSQL 16 and a real Next.js server, not mocks:

| # | Check | Result |
| --- | --- | --- |
| 1 | `pnpm auth:migrate` creates the `auth` schema | 5 tables |
| 2 | JWKS publishes an ES256 P-256 key | `{"alg":"ES256","crv":"P-256","kty":"EC",…}` |
| 3 | Sign-up assigns `role: student` server-side | ✓ |
| 4 | `/api/auth/token` mints a 15-minute JWT with `sub`, `sid`, `iss`, `aud` | ✓ (900s) |
| 5 | FastAPI verifies it and lazily provisions the profile | `200` + envelope |
| 6 | Admin route with a student token | `403 FORBIDDEN` |
| 7 | Invalid timezone on `PATCH /me` | `422` with field path `timezone` |
| 8 | `{"role":"admin"}` on `PATCH /me` | `422` "Extra inputs are not permitted" |
| 9 | Revoke, then reuse the token | `401 SESSION_REVOKED` |
| 10 | Promote to admin in DB, re-sign-in, admin route | `200` — profile role self-healed |
| 11 | Audit log holds events from **both** services, interleaved | 6 rows |

---

## 5. Test coverage

| Suite | Count | Focus |
| --- | --- | --- |
| `backend/tests/unit/test_security.py` | 14 | Token forgery, expiry, key rotation, JWKS caching |
| `backend/tests/unit/test_envelope.py` | 10 | The response contract and its mechanism |
| `backend/tests/integration/test_auth_router.py` | 23 | Full HTTP stack against real Postgres |
| `web/tests/schemas.test.ts` | 28 | Validation rules |
| `web/tests/api-client.test.ts` | 17 | Token lifecycle, retry bounds, error mapping |
| `web/tests/login-form.test.tsx` | 9 | Behaviour + accessibility |
| `web/tests/register-form.test.tsx` | 10 | Behaviour + escalation resistance |
| **Total** | **111** | |

Backend tests apply **real Alembic migrations** and the **real Better Auth DDL**
(`infra/postgres/reference/auth-schema.sql`), so a broken migration or an ORM
mapping that has drifted from the identity schema fails the suite rather than a
deploy.

Quality gates: `ruff` clean, `mypy --strict` clean (30 files), `tsc --noEmit`
clean, `next build` succeeds.

---

## 6. Two bugs found and fixed during implementation

**Correlation id missing on 500 responses.** Starlette's `ServerErrorMiddleware`
— which invokes the catch-all exception handler — sits *outside* the request
middleware, so the `ContextVar` holding the request id had already been reset by
the time the handler ran. The id was therefore absent precisely on the responses
where it matters most for debugging. Fixed by also stashing it on `request.state`
and reading through `request_id_of(request)`.

**Ambiguous password-toggle labels.** The sign-up form has two password fields,
each with a "Show password" button — indistinguishable to a screen-reader user
navigating by button list. The toggle now names its field ("Show confirm
password"). Found because a test could not disambiguate them either.

---

## 7. Known technical debt

Ordered by when it should be paid down.

| Item | Impact | Trigger |
| --- | --- | --- |
| **Email sent synchronously with the request** | A slow provider slows sign-up | First background worker (ARQ) |
| **API types hand-mirrored in TypeScript** | Contract can drift between languages | **Feature 2** — adopt `openapi-typescript` |
| **No CSP header** | Weaker XSS defence in depth | Before public launch; needs nonce threading |
| **No rate limiting on domain endpoints** | Abuse of `/api/v1` | Before public launch |
| **`pnpm.overrides.better-call`** | Non-obvious version pin | Remove when `@better-auth/cli` ≥ 1.6 ships |
| **Common-password list is a small hardcoded set** | Weak passwords pass | Swap for the HaveIBeenPwned k-anonymity range API |
| **Audit-log partition job not yet written** | Rows fall into the default partition, blocking new attachments | Before month 24 (partitions pre-created to then) |
| **Better Auth major upgrade = coordinated migration** | Column changes across two tools | Mitigated: only 10 stable columns are mapped |

---

## 8. Operating it

```bash
cp .env.example .env
# BETTER_AUTH_SECRET and POSTGRES_PASSWORD are required — compose refuses to start without them
openssl rand -base64 32     # BETTER_AUTH_SECRET
openssl rand -hex 16        # POSTGRES_PASSWORD

docker compose up -d postgres redis
./scripts/migrate.sh        # better-auth → alembic, in that order
docker compose up
```

Verification emails print to the web container's logs when `RESEND_API_KEY` is
unset, so the whole flow works locally with no third-party account.

**Promoting an admin** (there is deliberately no self-service path):

```sql
UPDATE auth."user" SET role = 'admin' WHERE email = 'someone@med.test';
```

The change takes effect on that user's next token; `user_profiles.role` heals
itself on the following request.

**Configuration that must agree across services** — a mismatch rejects every
token:

| Web | Backend |
| --- | --- |
| `BETTER_AUTH_URL` | `AUTH_ISSUER` |
| `AUTH_AUDIENCE` | `AUTH_AUDIENCE` |
| `DATABASE_URL` | `DATABASE_URL` |

---

## 9. What this feature leaves behind for the next one

- `require_role(...)` and `get_verified_user` — proven guards, ready to use.
- `user_profiles.user_id` — the FK target every future table should reference.
- The response envelope, applied automatically by `create_router`.
- `TextField` / `PasswordField` / `Alert` / `Button(loading)` — the form and
  loading-state vocabulary.
- `apiRequest` — token handling, retry, and error normalisation done once.
- A test harness with real Postgres, real migrations, and real signing keys.
