# API Reference

> Updated with every feature. Current scope: **Features 1–3 — Authentication, Courses, Media**.

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

## 4b. Catalogue endpoints (FastAPI)

All require an authenticated **and email-verified** caller. Draft or archived
content returns `404`, never `403`, so these endpoints cannot be used to probe
for unreleased courses.

### `GET /api/v1/courses`

One cursor-paginated page of the published catalogue, newest first.

| Query | Type | Notes |
| --- | --- | --- |
| `q` | string ≤120 | Matches title, subtitle, or specialty (case-insensitive) |
| `specialty` | string ≤120 | Exact match |
| `difficulty` | enum | `foundation` \| `intermediate` \| `advanced` |
| `limit` | int 1–100 | Default 20 |
| `cursor` | string | Opaque; from the previous page's `next_cursor` |

```json
{
  "success": true,
  "data": {
    "items": [{
      "id": "5b94d3e9-…", "slug": "clinical-cardiology",
      "title": "Clinical Cardiology", "subtitle": null,
      "specialty": "Cardiology", "difficulty": "intermediate",
      "status": "published", "cover_image_key": null,
      "lesson_count": 3, "total_duration_seconds": 2700,
      "published_at": "2026-07-26T13:40:52.757006Z"
    }],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 20 }
  },
  "message": ""
}
```

A malformed `cursor` or an unknown `difficulty` returns `422 VALIDATION_ERROR`
with the offending field named. `limit` above 100 is rejected rather than
silently clamped — an unbounded page size is a cheap denial-of-service.

### `GET /api/v1/courses/{slug}`

A published course with its outline. Adds `description`, `created_at`,
`updated_at`, and `modules[]`, each carrying `lessons[]`. **Unpublished lessons
are excluded at the query level**, so they never reach the response.

### `GET /api/v1/courses/{slug}/lessons/{lesson_slug}`

A single published lesson within a published course. Both must be published —
the guards compose, so a published lesson inside a draft course stays invisible.

---

## 4c. Admin authoring endpoints (FastAPI)

Every route below requires role `admin`, enforced by a guard declared **once on
the router**. The role is re-read from Postgres, not taken from the token claim.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/admin/courses` | List all courses; `?status=` filters |
| `POST` | `/api/v1/admin/courses` | Create a **draft** course → `201` |
| `GET` | `/api/v1/admin/courses/{id}` | Course with full outline, drafts included |
| `PATCH` | `/api/v1/admin/courses/{id}` | Partial update |
| `POST` | `/api/v1/admin/courses/{id}/publish` | Publish, cascading to draft lessons |
| `POST` | `/api/v1/admin/courses/{id}/archive` | Remove from the catalogue |
| `POST` | `/api/v1/admin/courses/{id}/modules` | Append a module → `201` |
| `PATCH` | `/api/v1/admin/modules/{id}` | Update a module |
| `DELETE` | `/api/v1/admin/modules/{id}` | Delete module + its lessons → `204` |
| `PUT` | `/api/v1/admin/courses/{id}/module-order` | Replace module order |
| `POST` | `/api/v1/admin/modules/{id}/lessons` | Append a lesson → `201` |
| `PATCH` | `/api/v1/admin/lessons/{id}` | Update a lesson |
| `POST` | `/api/v1/admin/lessons/{id}/publish` | Make a lesson visible |
| `POST` | `/api/v1/admin/lessons/{id}/unpublish` | Hide without deleting |
| `DELETE` | `/api/v1/admin/lessons/{id}` | Delete a lesson → `204` |
| `PUT` | `/api/v1/admin/modules/{id}/lesson-order` | Replace lesson order |

**Create/update bodies** accept `title` (required on create), `slug`, `subtitle`,
`description`, `specialty`, `difficulty`. `status` is **absent by design** —
publishing runs checks, and a writable status field would bypass them. Unknown
fields are rejected with `422`.

**Slugs.** Omitted → derived from the title, deduplicated (`anatomy`,
`anatomy-2`). Supplied but malformed → `422` with the corrected form suggested,
never a silent rewrite. A published course's slug is immutable → `409 CONFLICT`.

**Publishing** an empty course → `422`; a published course with no lessons is a
broken landing page. Publishing is idempotent and preserves the original
`published_at`.

**Reordering** replaces the whole sibling set:

```json
PUT /api/v1/admin/modules/{id}/lesson-order
{ "ordered_ids": ["uuid-c", "uuid-a", "uuid-b"] }

→ { "success": true, "data": { "items": [
      { "id": "uuid-c", "position": 0 },
      { "id": "uuid-a", "position": 1 },
      { "id": "uuid-b", "position": 2 } ] }, "message": "" }
```

The list must contain **exactly** the current members. A partial list or a
foreign id returns `422` — otherwise omitted items would be silently relocated,
or content dragged in from another course.

---

## 4d. Media endpoints

### `POST /api/v1/admin/media/uploads` — admin

Request a direct-upload credential. **The API never receives the file.**

```jsonc
// request
{ "kind": "lesson_video", "filename": "lecture.mp4",
  "content_type": "video/mp4", "size_bytes": 524288000 }

// 201
{ "success": true, "data": {
    "asset_id": "…", "upload_url": "https://…r2.cloudflarestorage.com/…?X-Amz-…",
    "method": "PUT", "headers": { "Content-Type": "video/mp4" },
    "expires_in_seconds": 900, "storage_key": "lesson_video/2026/07/….mp4" },
  "message": "" }
```

Send the bytes to `upload_url` with the given `method` and **the headers exactly
as returned** — they are part of the signature. Then confirm.

| Kind | Accepted types | Max size |
| --- | --- | --- |
| `lesson_video` | `video/mp4`, `video/webm`, `video/quicktime` | 2 GB |
| `course_cover` | `image/jpeg`, `image/png`, `image/webp` | 10 MB |
| `lesson_attachment` | `application/pdf` | 50 MB |

The object key is server-generated and its extension comes from the declared
content type, never the filename.

### `POST /api/v1/admin/media/uploads/{asset_id}/confirm` — admin

Marks the asset ready. **The server HEADs the object in storage first** and reads
back its real size — a client's claim that the upload happened is not evidence.
Idempotent.

| Outcome | Response |
| --- | --- |
| Object present, within limits | `200`, asset `ready` |
| Object absent | `409 CONFLICT` — retry the *upload*, not this call |
| Object oversized | `422` — the object is **deleted** and the asset marked `failed` |

### `DELETE /api/v1/admin/media/assets/{asset_id}` — admin

Deletes the object and the row → `204`. Any lesson or course referencing it has
its reference set to null; the content itself is untouched.

### Attachment — admin

| Method | Path | Purpose |
| --- | --- | --- |
| `PUT` | `/api/v1/admin/lessons/{id}/video` | Attach a ready `lesson_video` asset |
| `DELETE` | `/api/v1/admin/lessons/{id}/video` | Detach (asset kept in storage) |
| `PUT` | `/api/v1/admin/courses/{id}/cover` | Attach a ready `course_cover` asset |
| `DELETE` | `/api/v1/admin/courses/{id}/cover` | Remove the cover |

Body: `{ "asset_id": "…" }`. An asset that is not `ready` → `409`; a kind
mismatch → `422`.

### `GET /api/v1/courses/{slug}/lessons/{lesson_slug}/playback`

A short-lived signed URL for the lesson's video. Requires a verified caller, and
the course and lesson must both be published.

```json
{ "success": true, "data": {
    "url": "https://…?X-Amz-Expires=300&…",
    "expires_in_seconds": 300, "content_type": "video/mp4",
    "duration_seconds": 900 }, "message": "" }
```

> The URL carries no identity — anyone holding it can read the object until it
> expires. Authorisation happens when the ticket is issued, which is why the TTL
> is minutes and a fresh ticket is issued per view rather than cached.

Returns `404` when the lesson has no video — the same response as a missing
lesson, so this cannot be used to enumerate which lessons have recordings ready.

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
