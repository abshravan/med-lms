# MedLMS — System Architecture

> Status: living document. Updated whenever a feature lands.
> Last updated: Feature 1 — Authentication.

---

## 1. Product scope

A medical education platform. Two personas:

| Persona | Capabilities |
| --- | --- |
| **Student** | Watch course videos, read lesson notes, download PDFs, track progress, bookmark lessons, generate AI flashcards, take quizzes, practise AI voice viva, view analytics, resume across web + mobile |
| **Admin** | Upload courses / videos / notes, author quizzes, manage students, view cohort analytics |

Target: **100,000 registered users**, ~5,000 concurrent, ~500 concurrent video streams, ~50 concurrent realtime viva sessions. Every decision below is sized against that, not against 100 users and not against 10 million.

---

## 2. Architectural style

**A modular monolith on each side of the wire, with hard module boundaries drawn where the microservice seams will eventually be.**

Why not microservices now:

- At 100k users a single FastAPI process behind a load balancer plus Postgres and Redis is not the bottleneck — origin bandwidth and LLM latency are.
- Microservices trade local function calls for network calls, and local transactions for distributed sagas. That cost is only worth paying when teams, not machines, need to scale independently.
- The refactor cost from *modular monolith → services* is low **if and only if** modules never reach into each other's tables. That rule is enforced from day one (§13).

Why not a single Next.js app with server actions doing everything:

- The AI workloads (flashcard generation, viva transcript scoring, embeddings) are Python-shaped and long-running. Node can do it, but the ecosystem tax is real.
- Video/transcode pipelines and background workers want a Python worker runtime that shares models and repositories with the API.

So: **Next.js owns rendering + identity; FastAPI owns domain + AI; both share one Postgres with strict schema ownership.**

```
┌──────────────┐    ┌──────────────┐
│ Web (Next15) │    │ Mobile (RN)  │
└──────┬───────┘    └──────┬───────┘
       │ cookie session    │ bearer session
       ▼                   ▼
┌─────────────────────────────────────┐
│ Next.js  /api/auth/*  (Better Auth) │  ← identity authority
│  · sessions, OAuth, verify, reset   │
│  · mints short-lived ES256 JWTs     │
│  · publishes JWKS                   │
└──────┬──────────────────────┬───────┘
       │ JWT                  │ JWKS (cached)
       ▼                      ▼
┌─────────────────────────────────────┐
│ FastAPI  /api/v1/*                  │  ← domain authority
│  routers → services → repositories  │
└──┬────────┬─────────┬────────┬──────┘
   │        │         │        │
   ▼        ▼         ▼        ▼
Postgres  Redis   Cloudflare  LLM APIs
                     R2      (Realtime)
```

---

## 3. Identity: the one genuinely contentious decision

The stack specifies **Better Auth**, which is a TypeScript library. It cannot run inside FastAPI. This is the single most important design question in the project, so it gets compared explicitly rather than assumed.

### Options

| | Approach | Pros | Cons |
| --- | --- | --- | --- |
| **A** | **Better Auth in Next.js is the identity authority. It mints short-lived ES256 JWTs. FastAPI verifies them offline against cached JWKS.** | Matches the specified stack. Email verification, password reset, OAuth, 2FA, org/admin plugins come for free and are already security-reviewed. No password material ever touches Python. Verification is a local signature check — zero network hops per request, scales linearly. | Two runtimes participate in auth. JWT revocation is not instantaneous (mitigated §3.3). Better Auth owns its tables, so migration ownership must be partitioned (§5.1). |
| **B** | Auth implemented natively in FastAPI (passlib + custom JWT + refresh rotation). | One runtime, one source of truth, instant revocation. | Re-implements password hashing policy, email verification, reset-token single-use semantics, OAuth callback handling, replay protection, rate limiting. Weeks of work, and every one of those is a place to introduce a CVE. Contradicts the chosen stack. |
| **C** | Hosted IdP (Clerk / Auth0 / WorkOS). | Least code, best-in-class security. | Per-MAU pricing becomes material at 100k users. Student PII for a medical-education product acquires a third-party data-residency question. Lock-in on the one component hardest to migrate. |

### Recommendation: **A**

Rationale: authentication is the classic "don't build it yourself" component, and Better Auth is a real, maintained implementation that already covers the flows this product needs. The JWT bridge is a well-understood pattern (it is exactly how any OIDC provider talks to a resource server), and offline verification is what makes it scale.

### 3.1 Token model

| Token | Issuer | Lifetime | Transport | Audience |
| --- | --- | --- | --- | --- |
| Session cookie | Better Auth | 7 days, refreshed daily | `httpOnly; Secure; SameSite=Lax` | Next.js only |
| Session bearer token | Better Auth (`bearer` plugin) | 7 days | Secure storage on mobile | Next.js only |
| **Access JWT** | Better Auth (`jwt` plugin) | **15 minutes** | `Authorization: Bearer` | **FastAPI** (`aud: med-lms-api`) |

The web client never stores the access JWT in `localStorage`. It fetches one from `/api/auth/token` on demand (same-origin, cookie-authenticated) and holds it in memory only. Mobile does the same using its bearer session token.

**Why asymmetric (ES256), not HS256:** with HS256 the signing secret would have to be shared with FastAPI, meaning every service that *verifies* can also *forge*. ES256 gives FastAPI a public key only. ES256 is chosen over EdDSA purely for interop — `PyJWT`'s JWK handling for `EC` keys is more broadly supported than for `OKP`.

### 3.2 JWKS caching

FastAPI fetches `GET {web}/api/auth/jwks` and caches the key set in Redis for 10 minutes, with an in-process fallback cache. On an unknown `kid` the cache is force-refreshed exactly once (guarded so a burst of unknown-kid requests cannot stampede the web service). This makes key rotation a non-event.

### 3.3 Revocation — accepted tradeoff

A 15-minute JWT cannot be un-issued cryptographically. On logout, ban, or password change, the issuer writes a denylist entry to Redis:

```
revoked:sid:<session-id>  → TTL 15m
revoked:uid:<user-id>     → TTL 15m   (ban / password change: kills all sessions)
```

FastAPI checks both on each authenticated request (two O(1) Redis reads, pipelined).

> **Tradeoff, stated plainly:** if Redis is unavailable, the denylist check **fails open** — a valid, unexpired signature is still accepted. Failing closed would convert a Redis blip into a total API outage. The residual exposure is bounded at 15 minutes for an already-authenticated user. For a future feature involving controlled substances or exam integrity, revisit and fail closed on the specific routes that need it rather than globally.

### 3.4 Authorization

Roles: `student`, `admin`. Carried as a JWT claim for cheap reads, **but** every `admin`-gated route re-reads the role from Postgres. Admin routes are low-traffic, so the extra query is free, and it removes the "privileges revoked 14 minutes ago but the token still says admin" window on the routes where it actually matters.

---

## 4. Authentication flows

### 4.1 Registration + verification

```
Browser         Next.js/BetterAuth      Postgres      Mail
  │ POST /api/auth/sign-up/email │          │          │
  ├──────────────────────────────>          │          │
  │                              │ insert user (scrypt)│
  │                              ├─────────>│          │
  │                              │ insert verification │
  │                              ├─────────>│          │
  │                              │ send verify link    │
  │                              ├────────────────────>│
  │ 200 {user, session}          │          │          │
  <──────────────────────────────┤          │          │
  │ GET /verify-email?token=...  │          │          │
  ├──────────────────────────────> mark emailVerified  │
```

Unverified users can sign in but are gated out of content routes by the `requireVerified` dependency — this keeps the funnel intact while still enforcing verification before anything valuable is served.

### 4.2 Calling the domain API

```
Browser ──1── GET /api/auth/token (cookie)         → Next.js → { token }  (15 min, memory only)
Browser ──2── GET /api/v1/auth/me  Bearer <token>  → FastAPI
                                                     ├ verify ES256 vs cached JWKS
                                                     ├ check iss / aud / exp
                                                     ├ Redis denylist lookup
                                                     └ load profile → envelope
        ──3── on 401 TOKEN_EXPIRED: refetch token once, retry once, else → /login
```

Retry is bounded to a single attempt to prevent a redirect loop when the session cookie itself is dead.

### 4.3 Password reset

Request → always returns 200 regardless of whether the email exists (no account enumeration) → single-use, 1-hour token → reset → **all sessions for that user revoked** (`revoked:uid:*` written to Redis, session rows deleted).

---

## 5. Data architecture

### 5.1 Schema ownership — the rule that keeps this maintainable

One Postgres database, two schemas, **two migration owners that never touch each other's tables**:

| Schema | Owner | Migrated by | Contents |
| --- | --- | --- | --- |
| `auth` | Better Auth | `better-auth` CLI (Node) | `user`, `session`, `account`, `verification`, `jwks` |
| `public` | Application | Alembic (Python) | `user_profiles`, `auth_audit_log`, and every future domain table |

FastAPI maps the `auth.user` table **read-only** (`managed_externally`) and Alembic's autogenerate is filtered to skip the `auth` schema entirely. Better Auth reaches its schema through a connection-level `search_path`.

> **Technical debt to watch:** a Better Auth major version that changes its table shape becomes a coordinated migration. Mitigation: application code never selects Better Auth columns beyond `id, email, name, image, emailVerified, role, banned` — a narrow, stable surface — and `user_profiles` holds everything product-specific.

### 5.2 ER diagram (Feature 1 scope, with forward-looking tables greyed in)

```
┌───────────────────────────┐
│ auth.user                 │  ← Better Auth owned
│ id (text, PK)             │
│ email (text, unique)      │
│ emailVerified (bool)      │
│ name, image               │
│ role (text)               │
│ banned, banReason         │
│ createdAt, updatedAt      │
└──────┬────────────────────┘
       │ 1
       │
       │ 1                              ┌──────────────────────────┐
┌──────▼────────────────────┐           │ auth.session             │
│ public.user_profiles      │           │ id, userId → user.id     │
│ user_id (text, PK, FK)    │           │ token, expiresAt, ip, ua │
│ display_name              │           └──────────────────────────┘
│ role (enum)               │
│ institution               │           ┌──────────────────────────┐
│ year_of_study (int)       │           │ auth.account             │
│ specialization            │           │ providerId, accountId    │
│ timezone, locale          │           │ password (scrypt hash)   │
│ onboarding_completed_at   │           └──────────────────────────┘
│ last_active_at            │
│ created_at, updated_at    │           ┌──────────────────────────┐
└──────┬────────────────────┘           │ auth.verification        │
       │ 1                              │ identifier, value, expiry│
       │                                └──────────────────────────┘
       │ *
┌──────▼────────────────────┐
│ public.auth_audit_log     │
│ id (uuid, PK)             │
│ user_id (nullable FK)     │
│ event (enum)              │
│ outcome (enum)            │
│ ip_address (inet)         │
│ user_agent, request_id    │
│ metadata (jsonb)          │
│ created_at                │
└───────────────────────────┘

── future (not in Feature 1) ──────────────────────────────────
courses ─< modules ─< lessons ─< lesson_assets
lessons ─< progress_records >─ user_profiles
lessons ─< bookmarks       >─ user_profiles
lessons ─< flashcard_decks ─< flashcards
courses ─< quizzes ─< questions ─< options
quizzes ─< quiz_attempts ─< quiz_answers
lessons ─< viva_sessions ─< viva_turns
```

### 5.3 Indexing and growth

`auth_audit_log` is the only table in Feature 1 that grows unboundedly (~10 rows/user/month → ~12M rows/year at 100k users). It is written on a hot path and read rarely, so:

- Indexed on `(user_id, created_at DESC)` and `(event, created_at DESC)`.
- **Declared `PARTITION BY RANGE (created_at)` from day one, monthly partitions.** Retrofitting partitioning onto a 12M-row table later is a migration with downtime; doing it now costs one extra line. A future maintenance job detaches partitions older than 24 months.

---

## 6. API design

### 6.1 Response envelope (non-negotiable, every endpoint)

```jsonc
// success
{ "success": true,  "data": { }, "message": "", "meta": { "request_id": "…" } }
// failure
{ "success": false, "data": null, "message": "Human readable",
  "error": { "code": "VALIDATION_ERROR", "details": [ { "field": "email", "message": "…" } ] },
  "meta": { "request_id": "…" } }
```

Enforced structurally: routers return domain objects, and a single response model plus exception-handler layer wraps them. A handler cannot accidentally return a bare dict — the envelope is applied centrally, not per-route.

### 6.2 Error codes

Stable, machine-readable, never reworded for UI purposes:

`VALIDATION_ERROR` · `UNAUTHENTICATED` · `TOKEN_EXPIRED` · `TOKEN_INVALID` · `SESSION_REVOKED` · `EMAIL_NOT_VERIFIED` · `ACCOUNT_BANNED` · `FORBIDDEN` · `NOT_FOUND` · `CONFLICT` · `RATE_LIMITED` · `UPSTREAM_UNAVAILABLE` · `INTERNAL_ERROR`

### 6.3 Versioning

All domain routes under `/api/v1`. Better Auth routes live under `/api/auth` on the Next.js origin and are versioned by the library, not by us.

---

## 7. Video streaming architecture (design only — not Feature 1)

Direct MP4 from object storage is rejected: no adaptive bitrate, no bandwidth control, trivial to scrape.

**Chosen:** upload → R2 → transcode worker → **HLS** (240p/480p/720p/1080p ladder) → R2 → served through Cloudflare CDN with **signed, short-TTL playlist URLs** bound to user + lesson. Segment URLs inherit the signature. Player is `hls.js` behind a `VideoPlayer` component that emits heartbeat progress events (throttled to 1 per 15s) to `/api/v1/progress`.

Tradeoff: HLS packaging adds pipeline complexity and a transcode cost per upload versus serving the source file. Justified by bandwidth savings on mobile and by making casual content theft meaningfully harder. DRM (Widevine/FairPlay) is deliberately out of scope — the cost/benefit does not land until there is content worth pirating at scale.

---

## 8. AI architecture (design only — not Feature 1)

Three distinct workloads, deliberately not collapsed into one service:

| Workload | Shape | Runtime |
| --- | --- | --- |
| **Flashcard generation** | Batch, minutes, idempotent | Background worker (ARQ) → LLM → structured output validated by Pydantic → `flashcard_decks` |
| **Quiz auto-generation / grading** | Batch + short sync | Same worker; free-text answers scored by rubric prompt |
| **Voice viva** | Realtime, bidirectional audio, sub-300ms | Dedicated WebSocket route, ephemeral session, provider = OpenAI Realtime or Gemini Live behind a `RealtimeProvider` interface |

**Provider abstraction is mandatory.** A `LLMProvider` / `RealtimeProvider` protocol sits between services and vendors so that a pricing change or an outage is a config swap, not a rewrite. This is the single highest-leverage abstraction in the system.

**Flashcard flow:** lesson notes → chunk → dedupe against existing cards by embedding similarity → generate → validate schema → persist as `pending` → optional admin review → publish. Generation is keyed on `(lesson_id, content_hash)` so re-running is idempotent and cheap.

**Viva flow:** client opens WS → FastAPI mints an ephemeral provider token (never exposing the platform API key to the browser) → audio frames proxied bidirectionally → transcript turns persisted → on session end a scoring job grades against the lesson rubric and writes to analytics. Proxying rather than direct-to-provider is chosen so that quota, abuse, and transcript retention stay under platform control — at the cost of one extra network hop.

---

## 9. Background workers

**ARQ** (Redis-backed, asyncio-native) over Celery: Celery's strength is a huge feature surface this product does not need, and it pulls in a heavier operational footprint. ARQ shares the asyncio event loop model with FastAPI, so services and repositories are reused verbatim between the API and the worker. If scheduling needs outgrow ARQ, the escape hatch is Temporal, not Celery.

Queues: `transcode`, `ai`, `email`, `analytics`. Separated so a slow transcode backlog cannot starve password-reset emails.

---

## 10. Deployment & Docker architecture

```
docker-compose.yml
├── postgres  (16-alpine, named volume, init SQL creates `auth` schema)
├── redis     (7-alpine, appendonly)
├── api       (FastAPI, uvicorn, depends_on: postgres healthy, redis healthy)
├── web       (Next.js standalone output)
└── worker    (ARQ — introduced with the first async feature, not Feature 1)
```

Both images are multi-stage. Production runs the same compose topology behind a managed load balancer; Postgres and Redis become managed services (RDS/Neon + ElastiCache/Upstash) — the compose services exist so local development is one command.

Every container: non-root user, healthcheck, no secrets baked into layers.

---

## 11. Security considerations

| Concern | Control |
| --- | --- |
| Password storage | scrypt via Better Auth. Never handled by application code. |
| Token forgery | Asymmetric ES256; FastAPI holds public keys only. |
| Token replay after logout | Redis denylist + 15-minute TTL (§3.3). |
| Account enumeration | Reset and register responses are indistinguishable for existing/non-existing emails. |
| Brute force | Redis sliding-window rate limits: 5 sign-ins / 15 min / (IP + email), 3 reset requests / hour / email. |
| XSS → token theft | Session cookie is `httpOnly`; access JWT lives in memory only, never `localStorage`. |
| CSRF | `SameSite=Lax` cookies + Better Auth origin checks. Domain API is JWT-bearer, so it is not cookie-authenticated and is structurally CSRF-immune. |
| Secrets | Env-only, validated at boot by Pydantic Settings / Zod. Boot fails loudly on a missing secret rather than defaulting to something insecure. |
| PII in logs | Structured logging with an explicit redaction list (`email`, `token`, `password`, `authorization`). |
| Transport | HSTS, TLS terminated at the edge. |
| Audit | Every auth-relevant event lands in `auth_audit_log` with request id, IP, and user agent. |

---

## 12. Scaling strategy

Ordered by when it will actually be needed, not by what is fun:

1. **Now** — stateless API containers, horizontal scale behind a load balancer. Sessions are in Postgres/Redis, so any container serves any request.
2. **Now** — connection pooling. At 100k users the pooler (PgBouncer, transaction mode) matters far more than query tuning.
3. **~10k DAU** — Redis read-through cache for hot, rarely-changing reads (course catalogue, lesson metadata). Auth is deliberately *not* cached beyond JWKS: it is already offline-verified.
4. **~25k DAU** — read replica for analytics queries; move heavy aggregation off the primary.
5. **~50k DAU** — partition/archive `auth_audit_log` and progress events; pre-aggregate analytics into rollup tables rather than querying raw events.
6. **Bandwidth-driven, any time** — CDN does the heavy lifting for video from day one; origin egress should stay near-flat as users grow.

---

## 13. Future microservice boundaries

Modules are structured so these seams can be cut without touching call sites beyond the service layer:

| Seam | Why it separates first | Trigger to extract |
| --- | --- | --- |
| **Identity** | Already physically separate (Next.js). | Effectively already done. |
| **Media pipeline** | CPU-bound, spiky, entirely async, no shared transactions. | First time transcode load affects API latency. |
| **AI / Realtime** | Different scaling curve (GPU/quota-bound), different failure modes, vendor-coupled. | First time LLM latency or quota affects unrelated endpoints. |
| **Analytics** | Read-heavy, eventually-consistent by nature, wants a columnar store eventually. | First time analytics queries impact primary DB. |
| **Core learning** (courses/lessons/progress) | Stays the monolith. | Never — this is the product. |

The enforcement rule: **a module may only reach another module through its service layer, never through its repositories or tables.** Cross-module foreign keys are permitted only into `user_profiles` and `courses`. Everything else goes through an interface. That single rule is what makes the seams above cheap later.

---

## 14. Feature module map

```
auth          ← Feature 1 (this milestone)
courses       ← catalogue, modules, lessons
media         ← upload, transcode, signed playback
notes         ← lesson notes + PDF assets
progress      ← watch progress, completion, resume-anywhere
bookmarks
flashcards    ← AI generation + review (SRS)
quizzes       ← authoring, attempts, grading
viva          ← realtime voice examination
analytics     ← student + cohort dashboards
admin         ← content + user management
```

Each is a vertical slice: `features/<name>/` on the frontend, `routers|services|repositories/<name>` on the backend. No feature ships without folder structure, schema, endpoints, validation, error handling, loading states, tests, and docs.
