# Database Schema

> Updated with every feature. Current scope: **Feature 1 — Authentication**.

One PostgreSQL 16 database, two schemas, **two migration owners that never touch
each other's tables**.

| Schema | Owner | Migrated by | Contents |
| --- | --- | --- | --- |
| `auth` | Better Auth | `better-auth` CLI (Node) | `user`, `session`, `account`, `verification`, `jwks` |
| `public` | Application | Alembic (Python) | `user_profiles`, `auth_audit_log` |

Rationale in [architecture.md §5.1](./architecture.md#51-schema-ownership--the-rule-that-keeps-this-maintainable).

---

## 1. Migration order

**Not optional.** `public.user_profiles` has a foreign key into `auth.user`, so
the identity schema must exist first.

```bash
./scripts/migrate.sh          # does all three steps in order
```

1. `pnpm auth:bootstrap` — creates the `auth` schema and the `pgcrypto` extension.
2. `pnpm auth:migrate` — Better Auth CLI creates/updates the `auth` tables.
3. `alembic upgrade head` — Alembic creates/updates the `public` tables.

Running Alembic first fails with an explicit message naming the fix rather than
an opaque "relation auth.user does not exist" halfway through.

`infra/postgres/reference/auth-schema.sql` is a committed `pg_dump` of the
identity schema. It is **not** a migration — it exists so a Better Auth upgrade
that changes a column shows up as a reviewable diff, and so the backend test
suite runs against the real identity DDL rather than an approximation.

---

## 2. Entity relationships

```
┌──────────────────────────────┐
│ auth.user            (BA)    │
│──────────────────────────────│
│ id            text      PK   │
│ email         text      UQ   │
│ emailVerified boolean        │
│ name          text           │
│ image         text           │
│ role          text           │◄── authoritative role
│ banned        boolean        │
│ banReason     text           │
│ banExpires    timestamptz    │
│ createdAt     timestamptz    │
│ updatedAt     timestamptz    │
└───┬───────┬──────────┬───────┘
    │1      │1         │1
    │       │          │
    │*      │*         │1
┌───▼─────────┐ ┌──────▼──────────┐ ┌─────────────────────────────┐
│auth.session │ │ auth.account    │ │ public.user_profiles        │
│─────────────│ │─────────────────│ │─────────────────────────────│
│id       PK  │ │id           PK  │ │user_id  text PK ─FK→ user.id│
│userId   FK  │ │userId       FK  │ │display_name    varchar(120) │
│token    UQ  │ │providerId  text │ │role     user_role  NOT NULL │
│expiresAt    │ │accountId   text │ │institution     varchar(200) │
│ipAddress    │ │password    text │ │year_of_study   integer      │
│userAgent    │ │  (scrypt hash)  │ │specialization  varchar(120) │
│impersonatedBy│ │accessToken     │ │timezone varchar(64) 'UTC'   │
└─────────────┘ │refreshToken     │ │locale   varchar(16) 'en'    │
                │scope            │ │onboarding_completed_at      │
┌─────────────┐ └─────────────────┘ │last_active_at               │
│auth.verifi- │                     │created_at / updated_at      │
│cation       │ ┌─────────────────┐ └──────────────┬──────────────┘
│─────────────│ │ auth.jwks       │                │
│id       PK  │ │─────────────────│                │ (no FK — see §4)
│identifier IX│ │id           PK  │                │
│value        │ │publicKey        │ ┌──────────────▼──────────────┐
│expiresAt    │ │privateKey (enc) │ │ public.auth_audit_log       │
└─────────────┘ │createdAt        │ │  PARTITION BY RANGE(created)│
                └─────────────────┘ │─────────────────────────────│
                                    │id         uuid   ┐ PK       │
                                    │created_at timestz┘          │
                                    │user_id    varchar(255)      │
                                    │event      auth_event        │
                                    │outcome    auth_outcome      │
                                    │ip_address inet              │
                                    │user_agent varchar(512)      │
                                    │request_id varchar(64)       │
                                    │metadata   jsonb             │
                                    └─────────────────────────────┘
```

---

## 3. `public.user_profiles`

Product-specific data for an authenticated user. **Every future feature
foreign-keys to `user_profiles.user_id`, not to `auth.user.id`** — that keeps a
change of identity provider from cascading through the whole domain schema.

| Column | Type | Null | Default | Notes |
| --- | --- | --- | --- | --- |
| `user_id` | `varchar(255)` | no | — | PK, FK → `auth.user(id)` `ON DELETE CASCADE` |
| `display_name` | `varchar(120)` | yes | — | Falls back to `auth.user.name` on read |
| `role` | `user_role` | no | `student` | Mirror of the authoritative value |
| `institution` | `varchar(200)` | yes | — | |
| `year_of_study` | `integer` | yes | — | `CHECK` 1–10 |
| `specialization` | `varchar(120)` | yes | — | |
| `timezone` | `varchar(64)` | no | `UTC` | Validated as an IANA zone on write |
| `locale` | `varchar(16)` | no | `en` | |
| `onboarding_completed_at` | `timestamptz` | yes | — | Set on first profile edit |
| `last_active_at` | `timestamptz` | yes | — | Written at most every 5 min |
| `created_at` / `updated_at` | `timestamptz` | no | `now()` | Server-side defaults |

**Indexes:** `pk_user_profiles(user_id)`, `ix_user_profiles_role`,
`ix_user_profiles_last_active_at`.

**Enum** `user_role`: `student`, `admin`.

Rows are created **lazily**, on the user's first authenticated API request,
rather than by a hook in the identity service. A user who registered while the
API was down still gets a profile the moment they use it. The insert is an
`ON CONFLICT DO UPDATE … RETURNING`, so two concurrent first-requests both
receive a row instead of one failing.

`last_active_at` is only written when the stored value is more than 5 minutes
stale — otherwise every authenticated request would carry an `UPDATE` for a field
nothing reads in real time.

---

## 4. `public.auth_audit_log`

Append-only trail of authentication-relevant events, **written by both services**:
Better Auth records register / login / verify / reset; FastAPI records token
rejections, denied access, logout, and profile changes. One chronological story
per user rather than two half-stories.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | no | Part of PK |
| `created_at` | `timestamptz` | no | Part of PK **and** the partition key |
| `user_id` | `varchar(255)` | yes | **Intentionally not a foreign key** |
| `event` | `auth_event` | no | |
| `outcome` | `auth_outcome` | no | `success` \| `failure` |
| `ip_address` | `inet` | yes | Unparseable values stored as `NULL` |
| `user_agent` | `varchar(512)` | yes | Truncated |
| `request_id` | `varchar(64)` | yes | Correlates with `X-Request-ID` |
| `metadata` | `jsonb` | yes | Non-sensitive context only |

**Enum** `auth_event`: `register`, `login`, `logout`, `email_verify`,
`password_reset_request`, `password_reset_complete`, `token_rejected`,
`access_denied`, `profile_update`.

**Indexes:** `(user_id, created_at)`, `(event, created_at)`.

### Why `user_id` is not a foreign key

Audit rows must survive user deletion — an audit trail that disappears when the
subject is deleted is not an audit trail. Failed events may also reference an
identity that never became a user.

### Why it is partitioned from day one

At 100k users this reaches roughly **12M rows/year**. Retrofitting partitioning
onto a table that size is a migration with downtime; declaring it now costs one
line. Partitioning is `RANGE (created_at)`, monthly, with 24 partitions
pre-created plus a `DEFAULT` partition.

A partitioned table's primary key must contain the partition key, hence the
composite `(id, created_at)`.

> **The default partition is a deliberate availability trade.** It guarantees an
> audit insert can never fail for want of a partition — an audit write must not be
> able to break a sign-in. The cost: attaching a new monthly partition later
> requires the default to hold no rows in that range. **The maintenance job must
> stay ahead of the calendar.** See §6.

### Never stored here

Passwords, tokens, session tokens, or reset links. `metadata` records *which*
fields changed, never their values:

```json
{ "fields": ["institution", "year_of_study", "onboarding_completed_at"] }
```

---

## 5. `auth` schema (Better Auth)

Created and migrated by the `better-auth` CLI. The API maps only `auth.user`, and
only these columns: `id`, `email`, `emailVerified`, `name`, `image`, `role`,
`banned`, `banReason`, `createdAt`, `updatedAt` — a narrow, stable surface.

**The API never writes to any table in this schema.** All identity mutation goes
through Better Auth's own endpoints. Alembic's `include_object` hook excludes the
schema entirely, so `--autogenerate` cannot emit a `DROP TABLE auth.user`.

`auth.jwks` holds the ES256 signing keys; private keys are encrypted at rest with
`BETTER_AUTH_SECRET`.

---

## 6. Operational follow-ups

| Task | When | Why |
| --- | --- | --- |
| Monthly partition-creation job | Before month 24 | Keeps rows out of the default partition, so new partitions can still be attached |
| Detach partitions older than 24 months | Ongoing | Retention; keeps the table small |
| PgBouncer (transaction mode) | Before ~10k DAU | At 100k users, pooling matters more than query tuning. `statement_cache_size=0` is already set for compatibility |
| Read replica | ~25k DAU | Move analytics off the primary |

---

## 7. Local inspection

```bash
docker compose exec postgres psql -U medlms -d med_lms

\dn                      -- schemas: auth, public
\dt auth.*               -- identity tables
\dt public.*             -- application tables + partitions
\d+ public.auth_audit_log -- partition layout
SELECT version_num FROM alembic_version;
```
