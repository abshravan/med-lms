# Dependency Graph

> Updated with every feature. Current scope: **Features 1–2 — Authentication, Courses**.

---

## 1. Service topology

```
                    ┌───────────────┐
   browser ────────▶│  web  :3000   │
   mobile ─────────▶│  Next.js 15   │
                    │  Better Auth  │◀── identity authority
                    └───┬───────┬───┘
                        │       │
            JWKS + JWT  │       │ pg (search_path=auth)
                        ▼       ▼
                 ┌───────────┐  ┌──────────────┐
   browser ─────▶│ api :8000 │─▶│ postgres:5432│
   (Bearer JWT)  │  FastAPI  │  │  auth │public│
                 └─────┬─────┘  └──────────────┘
                       │
                       ▼
                 ┌───────────┐
                 │redis :6379│  JWKS cache · revocation deny-list
                 └───────────┘
```

**Direction of trust.** `api` depends on `web` for public signing keys only. It
never receives a secret from it, and cannot mint a token — only verify one. The
dependency is one-way and read-only, which is what makes it safe for `api` to
scale horizontally without coordinating with `web`.

`web → postgres` is limited to the `auth` schema, enforced by the connection's
`search_path`. Domain data is reached only through `api`.

---

## 2. Backend module graph

```
                    main.py
                       │
        ┌──────────────┼───────────────┐
        ▼              ▼               ▼
   middleware/      routers/      core/config
   ├ request_ctx    ├ auth        core/logging
   └ error_handler  └ health
                       │
                       ▼
              core/dependencies ──────┐
                       │              │
        ┌──────────────┼──────────┐   │
        ▼              ▼          ▼   ▼
   core/security  services/   core/database
        │         auth_service      │
        ▼              │            │
   core/redis ◀────────┤            │
                       ▼            ▼
              repositories/    (AsyncSession)
              user_repository
                       │
                       ▼
                   models/
              ├ auth (read-only)
              ├ profile
              ├ course
              └ base
```

The catalogue follows the identical chain — `routers/courses` and
`routers/admin_courses` → `services/course_service` →
`repositories/course_repository` → `models/course` — plus two leaf utilities
(`utils/slug`, `utils/pagination`) that depend on nothing but the stdlib and
`core/exceptions`. Adding a second feature required no change to any layer
contract, which is the point of fixing them in Feature 1.

Acyclic by construction. Every arrow points toward more stable code: routers
change often, `models` and `core` rarely.

**Layer contract**

| Layer | Depends on | Forbidden |
| --- | --- | --- |
| `routers` | services, schemas, dependencies | repositories, error shaping |
| `services` | repositories, models, core | FastAPI, HTTP concepts |
| `repositories` | models, SQLAlchemy | commits, business rules |
| `models` | SQLAlchemy | services, schemas |
| `core` | third-party only | feature modules |

`core/envelope` and `middleware/error_handler` are the only modules that
construct a response body. That is what makes the envelope contract structural
rather than a convention reviewers must police.

---

## 3. Frontend module graph

```
   app/(auth)/*            app/(app)/*            app/api/auth/[...all]
   login · register        layout (session gate)         │
   forgot · reset          dashboard                     │
        │                       │                        │
        ▼                       ▼                        ▼
   features/auth/components ────┴──────────▶  lib/auth/server ──▶ lib/auth/db
        │        │                                │    │              │
        │        ▼                                │    ▼              ▼
        │   components/common ──▶ components/ui   │  lib/email      pg Pool
        │        │                                │    │
        ▼        ▼                                │    ▼
   features/auth/hooks                            │  lib/email/templates
        │        │                                │
        │        ▼                                └──▶ lib/auth/audit
        │   features/auth/api
        │        │
        ▼        ▼
   lib/auth/client        lib/api/client ──▶ lib/api/errors ──▶ types/api
        │                        │
        └────────┬───────────────┘
                 ▼
             lib/env  (zod-validated)
```

**Server / client split.** `lib/auth/server.ts`, `lib/auth/db.ts`, and
`lib/auth/audit.ts` are server-only — they import `pg`. They are reachable from
route handlers and server components, never from a `"use client"` module.
`serverExternalPackages: ["pg"]` in `next.config.ts` prevents `pg` from being
bundled into a client or edge chunk.

`lib/env.ts` enforces the same split at the type level: `clientEnv` exposes only
`NEXT_PUBLIC_*` names, so a secret cannot be imported into the browser bundle by
accident.

---

## 4. Request flow: an authenticated API call

```
ProfileCard
  └─ useProfile (TanStack Query)
      └─ fetchProfile
          └─ api.get → apiRequest
              ├─ GET /api/auth/token          ← cookie-authenticated, same-origin
              │   └─ (memory cache; single-flight; 60s refresh margin)
              └─ GET :8000/api/v1/auth/me     ← Authorization: Bearer
                    │
                    ├─ RequestContextMiddleware   correlation id
                    ├─ get_token_claims           ES256 verify vs cached JWKS
                    ├─ get_current_user           Redis deny-list → DB → profile
                    ├─ read_me                    service → repository
                    ├─ EnvelopedRoute             wrap in {success, data, message}
                    └─ error_handler              on any failure
```

On `401 TOKEN_EXPIRED`, the client refreshes once and retries once — then gives
up. An unbounded retry here would spin whenever the underlying session is dead.

---

## 5. Package rationale

Only choices that were not obvious are listed. Rule 18: a non-default library
needs a reason.

### Backend

| Package | Chosen over | Why |
| --- | --- | --- |
| **PyJWT[crypto]** | python-jose, authlib | Maintained, minimal, first-class JWKS. python-jose has a poor CVE record and is effectively unmaintained. |
| **asyncpg** | psycopg3 | Fastest async PostgreSQL driver; SQLAlchemy 2 supports it natively. `statement_cache_size=0` set for PgBouncer transaction mode. |
| **structlog** | stdlib logging | Structured output by default, and a processor pipeline — which is how PII redaction is enforced mechanically rather than by review. |
| **pydantic-settings** | os.environ | Validates the whole env contract at boot; a missing secret fails the start instead of surfacing as a 500 later. |
| **redis-py (asyncio)** | aioredis | aioredis was merged into redis-py; it is the maintained path. |
| **fakeredis** | mocks / testcontainers | Implements real `SET`/`EXISTS`/TTL semantics, which is exactly what the deny-list depends on — a mock would assert on calls, not behaviour. |
| **respx** | responses / manual patching | Intercepts at the httpx transport, so the real JWKS fetch-and-cache path is exercised with nothing stubbed inside `core/security`. |
| **ARQ** *(planned)* | Celery | asyncio-native, so services and repositories are reused verbatim between API and worker. Celery's breadth is not needed and its ops footprint is larger. Escape hatch if outgrown: Temporal, not Celery. |

### Frontend

| Package | Chosen over | Why |
| --- | --- | --- |
| **pg (raw driver)** | Prisma, Drizzle | Better Auth's Kysely adapter takes a `pg.Pool` directly. Adding an ORM would mean a second schema definition and a second migration tool in a repo where Alembic already owns the domain schema — two sources of truth for one database. |
| **TanStack Query** | SWR, RTK Query | Best-in-class cache invalidation and a retry predicate, which is needed here: 401/403 must **not** be retried, only transient failures. |
| **zod** | yup, joi | Type inference means one schema defines both validation and the TypeScript type — no drift between them. |
| **react-hook-form** | Formik | Uncontrolled by default, so typing in a form does not re-render the whole tree; matters on the long registration form. |
| **Resend via `fetch`** | SES/Postmark SDK | No SDK dependency at all. The `EmailTransport` interface is the real seam — swapping providers is one small class. |
| **Native checkbox** | `@radix-ui/react-checkbox` | `register()` binds directly to native inputs; the Radix version needs a `Controller` per use and buys nothing without a custom indicator. |
| **No zxcvbn** | zxcvbn | ~800 kB for an advisory meter on the critical registration path. A heuristic is used instead; the real rule is enforced by zod and the server. |

### Notable exclusions

| Not used | Why |
| --- | --- |
| `jwtClient()` from better-auth | Its only client action fetches JWKS, which the browser has no use for — verification happens in FastAPI. In better-auth 1.6.x its declared types also conflict with the client's fetch types. |
| A CSP header | Next.js injects inline bootstrap scripts, so a correct policy needs per-request nonces through middleware. Shipping `unsafe-inline` would look like protection while providing none. Tracked as follow-up. |
| `openapi-typescript` codegen | One endpoint group does not justify the machinery. **Adopt it at the second feature** — hand-maintaining a growing contract in two languages is how they drift. |

---

## 6. Version constraints worth knowing

| Constraint | Reason |
| --- | --- |
| `pnpm.overrides.better-call: 1.3.7` | `@better-auth/cli` (latest stable 1.4.22) lags `better-auth` 1.6.25 and resolves an older `better-call` that lacks an export the newer core requires. The override reconciles them so `pnpm auth:migrate` works. **Remove once the CLI catches up.** |
| Access-token TTL: 15 min | Must match `ACCESS_TOKEN_EXPIRY` in `web/src/lib/auth/server.ts` and `ACCESS_TOKEN_TTL_SECONDS` in `backend/app/services/auth_service.py`. The latter sizes the revocation deny-list; if it were shorter, a revoked token would become usable again before expiring. |
| `AUTH_AUDIENCE` | Must be byte-identical on both sides, or every token is rejected as "not issued for this API". |
| `BETTER_AUTH_URL` = `AUTH_ISSUER` | The `iss` claim is verified strictly. |
| ES256, not the EdDSA default | `PyJWT`'s JWK support for EC keys is more broadly available than for OKP. Interop with the Python verifier outweighs Ed25519's marginal benefits. |
