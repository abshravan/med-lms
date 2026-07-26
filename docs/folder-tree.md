# Folder Structure

> Updated with every feature. Current scope: **Feature 1 — Authentication**.

```
med-lms/
├── docker-compose.yml            postgres · redis · api · web
├── .env.example                  compose environment contract
├── docs/
│   ├── architecture.md           system design, decisions, tradeoffs
│   ├── api.md                    endpoint reference
│   ├── database.md               schema, ER diagram, migration order
│   ├── dependency-graph.md       module dependencies + package rationale
│   └── features/
│       └── authentication.md     Feature 1 implementation notes
├── infra/
│   └── postgres/
│       ├── init/01-schemas.sql               runs on first container init
│       └── reference/auth-schema.sql         pg_dump of the identity schema
├── scripts/
│   └── migrate.sh                enforces the better-auth → alembic order
│
├── backend/                      ── FastAPI domain API ──
│   ├── pyproject.toml
│   ├── Dockerfile                base → development → production (non-root)
│   ├── alembic.ini
│   ├── .env.example
│   ├── alembic/
│   │   ├── env.py                excludes the externally-owned `auth` schema
│   │   └── versions/
│   │       └── …_0001_auth_foundation.py
│   ├── app/
│   │   ├── main.py               application factory + lifespan
│   │   ├── core/                 cross-cutting concerns
│   │   │   ├── config.py         pydantic-settings; fails boot on a bad value
│   │   │   ├── database.py       async engine + session dependency
│   │   │   ├── redis.py          client + revocation deny-list
│   │   │   ├── security.py       JWKS cache + ES256 token verification
│   │   │   ├── dependencies.py   the auth/authz dependency chain
│   │   │   ├── envelope.py       response-envelope route class
│   │   │   ├── exceptions.py     domain errors + stable error codes
│   │   │   └── logging.py        structlog + PII redaction
│   │   ├── models/               SQLAlchemy ORM
│   │   │   ├── base.py           declarative base, naming convention
│   │   │   ├── auth.py           read-only mapping of auth.user
│   │   │   └── profile.py        user_profiles, auth_audit_log
│   │   ├── schemas/              Pydantic — the API contract
│   │   │   ├── common.py         envelope, pagination
│   │   │   └── auth.py
│   │   ├── repositories/         the only layer that knows SQLAlchemy
│   │   │   ├── base.py
│   │   │   └── user_repository.py
│   │   ├── services/             business logic + transaction boundaries
│   │   │   └── auth_service.py
│   │   ├── routers/              HTTP surface, one module per feature
│   │   │   ├── auth.py
│   │   │   └── health.py
│   │   ├── middleware/
│   │   │   ├── request_context.py  correlation id, access log
│   │   │   └── error_handler.py    every error response is built here
│   │   └── utils/
│   └── tests/
│       ├── conftest.py           real Postgres, real migrations, real ES256 keys
│       ├── unit/
│       │   ├── test_security.py  token forgery, expiry, rotation, alg confusion
│       │   └── test_envelope.py  the response contract itself
│       └── integration/
│           └── test_auth_router.py
│
└── web/                          ── Next.js 15 app + identity authority ──
    ├── package.json
    ├── Dockerfile                deps → build → production (standalone, non-root)
    ├── next.config.ts            security headers, standalone output
    ├── vitest.config.ts
    ├── .env.example
    ├── scripts/auth-bootstrap.ts creates the `auth` schema
    ├── tests/                    vitest + testing-library
    │   ├── schemas.test.ts
    │   ├── api-client.test.ts
    │   ├── login-form.test.tsx
    │   └── register-form.test.tsx
    └── src/
        ├── middleware.ts         redirect optimisation — NOT a security boundary
        ├── app/                  routes only; no business logic
        │   ├── layout.tsx
        │   ├── providers.tsx     per-request QueryClient
        │   ├── error.tsx · not-found.tsx · page.tsx
        │   ├── api/auth/[...all]/route.ts    Better Auth handler
        │   ├── (auth)/           unauthenticated: login, register,
        │   │                     forgot-password, reset-password, verify-email
        │   └── (app)/            authenticated shell — the real session gate
        │       └── dashboard/
        ├── components/
        │   ├── ui/               shadcn-style primitives (button, input, …)
        │   └── common/           composed, app-aware (text-field, app-header)
        ├── features/             vertical slices
        │   └── auth/
        │       ├── api/          domain-API calls
        │       ├── components/   forms and views
        │       ├── hooks/        TanStack Query hooks
        │       ├── schemas/      zod — one source of truth for form rules
        │       └── types/        mirrors backend/app/schemas/auth.py
        ├── hooks/                cross-cutting hooks (see its README)
        ├── services/             cross-cutting client services (see its README)
        ├── lib/
        │   ├── env.ts            zod-validated env; server vs public split
        │   ├── utils.ts          cn()
        │   ├── auth/
        │   │   ├── server.ts     Better Auth config — the identity authority
        │   │   ├── client.ts     browser client
        │   │   ├── db.ts         pg pool, search_path=auth
        │   │   └── audit.ts      identity-side audit writes
        │   ├── api/
        │   │   ├── client.ts     token lifecycle, envelope unwrapping, retry
        │   │   └── errors.ts     ApiError
        │   ├── email/            transport interface + templates
        │   └── query/client.ts   TanStack Query defaults
        └── types/api.ts          envelope types
```

---

## Placement rules

These are what keep the structure from decaying as features are added.

### Backend

| Layer | May depend on | Must never |
| --- | --- | --- |
| `routers/` | `services`, `schemas`, `core.dependencies` | Touch a repository or build an error body |
| `services/` | `repositories`, `models`, `core` | Import FastAPI, or know about HTTP |
| `repositories/` | `models`, SQLAlchemy | Commit, or contain business rules |
| `models/` | SQLAlchemy only | Import a service or schema |
| `core/` | stdlib + third-party | Import a feature module |

Transactions are owned by the service layer, so one business operation spanning
several repositories stays atomic.

### Frontend

| Directory | Holds | Rule |
| --- | --- | --- |
| `app/` | Routing, layouts, metadata | No business logic; delegates to `features/` |
| `components/ui/` | Generic primitives | No app or domain knowledge |
| `components/common/` | Composed, app-aware pieces | Used by ≥2 features |
| `features/<name>/` | A vertical slice | **Never imports another feature** |
| `lib/` | Framework-agnostic infrastructure | No React components |
| `hooks/`, `services/` | Cross-cutting only | Promote here only on the *second* consumer |

The rule that matters most: **a feature never imports another feature.** Shared
code moves down into `components/common`, `lib`, `hooks`, or `services`. That is
what keeps the future service seams in
[architecture.md §13](./architecture.md#13-future-microservice-boundaries) cheap
to cut.

---

## Adding a feature

1. `backend/app/{models,schemas,repositories,services,routers}/<feature>.py`
2. `alembic revision --autogenerate -m "<feature>"`, then read the generated SQL
3. `web/src/features/<feature>/{api,components,hooks,schemas,types}/`
4. Tests on both sides — a feature is not done without them
5. Update `docs/api.md`, `docs/database.md`, this file, and
   `docs/dependency-graph.md` (project rule 17)
