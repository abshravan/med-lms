# API Reference

> Updated with every feature. Current scope: **Feature 1 — Authentication**.

Two API surfaces, on two origins, with different owners:

| Surface | Origin | Owner | Purpose |
| --- | --- | --- | --- |
| `/api/auth/*` | Next.js (`:3000`) | Better Auth | Credentials, sessions, tokens |
| `/api/v1/*` | FastAPI (`:8000`) | Application | Domain data |

---

## 1. Response envelope

Every `/api/v1` response uses this shape. No exceptions — it is applied by the
route layer, not by individual handlers (`backend/app/core/envelope.py`).

**Success**

```json
{
  "success": true,
  "data": { },
  "message": "",
  "meta": { "request_id": "0b4f…" }
}
```

**Failure**

```json
{
  "success": false,
  "data": null,
  "message": "The submitted data is invalid.",
  "error": {
    "code": "VALIDATION_ERROR",
    "details": [{ "field": "year_of_study", "message": "Input should be less than or equal to 10" }]
  },
  "meta": { "request_id": "0b4f…" }
}
```

`data` is always present, and always `null` on failure, so clients can index the
key unconditionally.

### Error codes

Stable and machine-readable. Branch on these, never on `message`.

| Code | HTTP | Meaning | Client should |
| --- | --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Input rejected | Show `error.details` against form fields |
| `UNAUTHENTICATED` | 401 | No token supplied | Redirect to `/login` |
| `TOKEN_EXPIRED` | 401 | Signature valid, `exp` passed | Refresh token, retry once |
| `TOKEN_INVALID` | 401 | Bad signature / issuer / audience | Refresh token, retry once, then sign in |
| `SESSION_REVOKED` | 401 | Signed out or banned | Redirect to `/login`. **Do not retry** |
| `EMAIL_NOT_VERIFIED` | 403 | Verification required | Send to `/verify-email` |
| `ACCOUNT_BANNED` | 403 | Account suspended | Show `message`; contact support |
| `FORBIDDEN` | 403 | Insufficient role | Show a denial; do not retry |
| `NOT_FOUND` | 404 | No such resource | — |
| `CONFLICT` | 409 | State conflict | — |
| `RATE_LIMITED` | 429 | Too many requests | Back off |
| `UPSTREAM_UNAVAILABLE` | 503 | Dependency down | Retry with backoff |
| `INTERNAL_ERROR` | 500 | Bug | Show `meta.request_id` for support |

### Correlation

Every response carries `X-Request-ID`, mirrored in `meta.request_id`. A
client-supplied `X-Request-ID` is honoured when it is ≤64 printable characters
with no whitespace; otherwise a fresh UUID is generated (a newline in that header
would allow log injection).

---

## 2. Authentication

`/api/v1` uses bearer access tokens minted by Better Auth.

```
Authorization: Bearer <access-token>
```

**Obtaining a token** — `GET http://localhost:3000/api/auth/token`, same-origin
and cookie-authenticated. Returns `{ "token": "<jwt>" }`.

| Property | Value |
| --- | --- |
| Algorithm | `ES256` (asymmetric — the API holds public keys only) |
| Lifetime | 15 minutes |
| `iss` | `BETTER_AUTH_URL` |
| `aud` | `med-lms-api` |
| Claims | `sub`, `sid`, `email`, `emailVerified`, `role`, `iat`, `exp` |

Verification is offline against the JWKS at `/api/auth/jwks`, cached in Redis for
10 minutes. The API makes no per-request call to the identity service.

> Never store the access token in `localStorage`. The web client holds it in
> memory only; the durable credential is the `httpOnly` session cookie.

---

## 3. Identity endpoints (Next.js, Better Auth)

Base: `http://localhost:3000/api/auth`

| Method | Path | Body | Purpose |
| --- | --- | --- | --- |
| `POST` | `/sign-up/email` | `{ name, email, password, callbackURL }` | Register; sends verification email |
| `POST` | `/sign-in/email` | `{ email, password, rememberMe }` | Sign in; sets session cookie |
| `POST` | `/sign-out` | — | Destroy the session |
| `GET` | `/get-session` | — | Current session, or `null` |
| `POST` | `/request-password-reset` | `{ email, redirectTo }` | Send reset link. **Always 200** |
| `POST` | `/reset-password` | `{ newPassword, token }` | Consume the reset token |
| `POST` | `/send-verification-email` | `{ email, callbackURL }` | Re-send verification |
| `GET` | `/verify-email?token=…` | — | Consume the verification token |
| `GET` | `/token` | — | Mint a 15-minute access token |
| `GET` | `/jwks` | — | Public signing keys |

Password policy: minimum 12 characters, maximum 128, hashed with scrypt.
Verification and reset tokens are single-use and expire after 1 hour.

> `request-password-reset` returns the same response whether or not the address
> exists. This is deliberate — a different response would let anyone enumerate
> which addresses are registered.

---

## 4. Domain endpoints (FastAPI)

Base: `http://localhost:8000`

### `GET /health`

Liveness. Touches no dependency. Always `200` if the process is serving.

```json
{ "success": true, "data": { "status": "ok" }, "message": "" }
```

### `GET /ready`

Readiness. `200` when Postgres and Redis are both reachable, `503` otherwise —
so a load balancer stops routing without the container being restarted.

```json
{ "success": true, "data": { "ready": true, "dependencies": { "database": true, "redis": true } }, "message": "" }
```

### `GET /api/v1/auth/me`

Returns the caller's profile. Creates the profile row on first call if it does
not exist yet.

**Auth:** required. Available to unverified users, so the client can render the
"verify your email" state.

```json
{
  "success": true,
  "data": {
    "user_id": "2kb3RAxo22L4a8ixLmM0shRojE000JYM",
    "email": "grace@med.test",
    "email_verified": false,
    "display_name": "Grace Hopper",
    "role": "student",
    "institution": null,
    "year_of_study": null,
    "specialization": null,
    "timezone": "UTC",
    "locale": "en",
    "onboarding_completed": false,
    "last_active_at": "2026-07-26T12:52:10.180005Z",
    "created_at": "2026-07-26T12:52:10.158947Z"
  },
  "message": "",
  "meta": { "request_id": "58ec1381-…" }
}
```

| Failure | Code |
| --- | --- |
| No/!valid token | 401 `UNAUTHENTICATED` / `TOKEN_INVALID` / `TOKEN_EXPIRED` |
| Signed out or banned | 401 `SESSION_REVOKED` |
| Account suspended | 403 `ACCOUNT_BANNED` |
| Token names a deleted user | 404 `NOT_FOUND` |

### `PATCH /api/v1/auth/me`

Partially update the caller's own profile. There is no `user_id` parameter — the
subject is always the caller.

**Body** (all optional; omitted fields are left untouched)

| Field | Type | Rule |
| --- | --- | --- |
| `display_name` | string | 1–120 chars, trimmed |
| `institution` | string | ≤200 chars, trimmed |
| `year_of_study` | integer | 1–10 |
| `specialization` | string | ≤120 chars, trimmed |
| `timezone` | string | A valid IANA zone (e.g. `Asia/Kolkata`) |
| `locale` | string | 2–16 chars |

Unknown fields are **rejected** with 422. `email` and `role` are deliberately
absent from the schema, so an attempt to change them fails validation before any
logic runs:

```json
{
  "success": false, "data": null,
  "message": "The submitted data is invalid.",
  "error": { "code": "VALIDATION_ERROR",
             "details": [{ "field": "role", "message": "Extra inputs are not permitted" }] }
}
```

The first successful update marks onboarding complete. Returns the updated
profile in the same shape as `GET /me`.

### `POST /api/v1/auth/sessions/revoke`

Deny-lists the caller's outstanding access token so it stops being accepted
immediately, rather than remaining valid for the rest of its 15-minute life. The
web client calls this *before* Better Auth's sign-out, while the token still
authenticates.

```json
{ "success": true, "data": { "revoked": true, "expires_in_seconds": 900 }, "message": "" }
```

If the token has no `sid`, the whole user is revoked instead — the only safe
scope in that case.

### `GET /api/v1/auth/session`

Non-sensitive diagnostics about the verified token. Exists so support can answer
"what does the API think my session is?" without anyone pasting a token into a
chat window. Contains no credential material and no email address.

```json
{
  "success": true,
  "data": {
    "user_id": "2kb3RAx…", "role": "student", "session_id": "zka4PoJ…",
    "email_verified": false,
    "expires_at": "2026-07-26T13:07:09Z", "seconds_until_expiry": 873
  },
  "message": ""
}
```

### `GET /api/v1/auth/admin/ping`

Confirms the caller holds the `admin` role. A minimal admin-gated endpoint that
makes the authorization guard testable end-to-end, so the first real admin
feature inherits a proven guard.

**Auth:** required, role `admin`.

The role is read from the **database**, not from the token claim. A token
asserting `role: admin` for a user who is a student in Postgres receives
`403 FORBIDDEN` — this closes the window where a token minted before a demotion
still claims the old role.

---

## 5. Rate limits

Enforced by Better Auth on the identity endpoints:

| Endpoint | Limit |
| --- | --- |
| `POST /sign-in/email` | 5 per 15 min per IP+email |
| `POST /request-password-reset` | 3 per hour per email |
| `POST /send-verification-email` | 3 per hour per email |

Domain endpoints are not yet rate-limited — noted as follow-up work in
`docs/features/authentication.md`.

---

## 6. Interactive documentation

FastAPI serves Swagger UI at `/docs` and the schema at `/openapi.json` in every
environment **except production**, where both are disabled — an unauthenticated
schema dump is free reconnaissance for an attacker.
