# Database Schema

> Updated with every feature. Current scope: **Features 1–3 — Authentication, Courses, Media**.

One PostgreSQL 16 database, two schemas, **two migration owners that never touch
each other's tables**.

| Schema | Owner | Migrated by | Contents |
| --- | --- | --- | --- |
| `auth` | Better Auth | `better-auth` CLI (Node) | `user`, `session`, `account`, `verification`, `jwks` |
| `public` | Application | Alembic (Python) | `user_profiles`, `auth_audit_log`, `courses`, `modules`, `lessons`, `media_assets` |

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

## 5b. Course catalogue

```
┌──────────────────────────────┐
│ public.courses               │
│──────────────────────────────│
│ id            uuid   PK      │
│ slug          varchar(160) UQ│  immutable once published
│ title         varchar(200)   │
│ subtitle      varchar(300)   │
│ description   text           │
│ specialty     varchar(120)   │
│ difficulty    course_difficulty
│ status        content_status │  draft | published | archived
│ cover_image_key varchar(512) │  R2 key; populated by Feature 3
│ published_at  timestamptz    │
│ created_by    → user_profiles│  ON DELETE SET NULL
│ created_at / updated_at      │
└──────┬───────────────────────┘
       │ 1:N  (ON DELETE CASCADE)
┌──────▼───────────────────────┐
│ public.modules               │
│──────────────────────────────│
│ id        uuid  PK           │
│ course_id uuid  FK           │
│ title     varchar(200)       │
│ summary   text               │
│ position  int                │  UNIQUE(course_id, position) DEFERRABLE
└──────┬───────────────────────┘
       │ 1:N  (composite FK, ON DELETE CASCADE)
┌──────▼───────────────────────┐
│ public.lessons               │
│──────────────────────────────│
│ id         uuid PK           │
│ module_id  uuid ┐            │
│ course_id  uuid ┘ composite FK → modules(id, course_id)
│ slug       varchar(160)      │  UNIQUE(course_id, slug)
│ title      varchar(200)      │
│ summary    text              │
│ content_type lesson_content_type   video | reading | quiz
│ duration_seconds int         │  CHECK > 0
│ is_free_preview  bool        │
│ status     content_status    │
│ position   int               │  UNIQUE(module_id, position) DEFERRABLE
│ published_at timestamptz     │
│ created_at / updated_at      │
└──────────────────────────────┘
```

**Enums:** `content_status` (`draft`/`published`/`archived`),
`course_difficulty` (`foundation`/`intermediate`/`advanced`),
`lesson_content_type` (`video`/`reading`/`quiz`).

**Indexes:** `ix_courses_status_published_at` (covers the catalogue's default
query), `ix_courses_specialty`, `ix_modules_course_id_position`,
`ix_lessons_module_id_position`, `ix_lessons_course_id_status` (serves the
per-course lesson-count aggregate).

### Two guarantees enforced by the schema

**A lesson's course cannot disagree with its module's.** `lessons.course_id` is
denormalised so future progress, bookmark, and quiz tables can filter by course
without a join. The foreign key is composite —
`(module_id, course_id) → modules(id, course_id)` — so Postgres rejects any
mismatch. The convenience is kept; the drift risk is removed.

**Reordering is atomic.** Both position constraints are
`DEFERRABLE INITIALLY DEFERRED`. A reorder rewrites every position in one
transaction and uniqueness is checked once at `COMMIT`, so the transient states
where two rows share a slot are legal. Without deferral, reordering would need
sparse positions (which drift) or a temporary-offset workaround.

**`ck_courses_published_has_timestamp`** makes a published course with a null
`published_at` impossible — that combination would break both the catalogue's
ordering and its pagination cursor.

### Deletion policy

| Entity | Policy | Why |
| --- | --- | --- |
| Course | **Archived**, never deleted | Progress, bookmarks, and quiz attempts will reference it |
| Module | Hard delete (cascades to lessons) | Organisational container; nothing points at it yet |
| Lesson | Hard delete | Same — **revisit before the progress feature** |

Deleting a module or lesson renumbers its remaining siblings so positions stay
contiguous; a gap would make the next append land on an unexpected index.

### Counts are computed, not stored

`lesson_count` and `total_duration_seconds` are aggregated per request rather
than kept as counter columns. Counters would need maintaining on insert, update,
delete, publish, and reorder — five places to forget — and drift silently when
one is missed. Course counts are in the hundreds, and the aggregate uses
`ix_lessons_course_id_status`.

> Revisit above ~10,000 courses, or if the catalogue query appears in slow logs.
> The fix is a trigger-maintained counter, not application-maintained.

---

## 5c. `public.media_assets`

One row per object in storage, created **before** the bytes exist.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `uuid` | PK |
| `kind` | `media_kind` | `lesson_video` \| `course_cover` \| `lesson_attachment` |
| `status` | `media_status` | `pending` → `ready` \| `failed` |
| `storage_key` | `varchar(512)` | **Unique.** Server-generated; a retried upload cannot overwrite a confirmed asset |
| `original_filename` | `varchar(255)` | Only for `Content-Disposition`; never used to build a path |
| `content_type` | `varchar(127)` | Bound into the upload signature |
| `size_bytes` | `bigint` | Client's claim until confirmation, then storage's real value. `bigint` because a 4 GB lecture overflows `int4` |
| `checksum` | `varchar(128)` | ETag or client-supplied |
| `confirmed_at` | `timestamptz` | Set when the object is verified present |
| `uploaded_by` | `varchar(255)` | FK → `user_profiles`, `ON DELETE SET NULL` |

**Constraints:** `ck_media_assets_size_non_negative`, and
`ck_media_assets_ready_is_confirmed` — a `ready` asset must have both
`confirmed_at` and `size_bytes`, so the verification step cannot be bypassed even
by a direct SQL write.

**Indexes:** `(status, created_at)` — serves the orphan-cleanup job;
`(uploaded_by)`.

### Linkage

`lessons.video_asset_id` and `courses.cover_asset_id` both reference
`media_assets.id` with `ON DELETE SET NULL`. Deleting a video must not delete the
lesson.

`Course.cover_asset` is a `lazy="joined"` relationship: every course read needs
the cover's storage key to build a signed URL, and lazy loading would mean one
extra `SELECT` per card in a 20-card catalogue grid.

> **Migration note.** `courses.cover_image_key` (a raw string, added in Feature 2
> and never populated) was replaced by the typed `cover_asset_id` foreign key.
> The API field became `cover_image_url` — a signed URL — because the raw storage
> key is a stable, guessable handle that clients have no use for.

### The lifecycle is the point

`status` is not decoration. With direct-to-storage uploads the API sees no bytes,
so `pending` genuinely means "a URL was issued and we do not know what happened".
`ready` is only set after the server HEADs the object. See
[features/media.md §2](./features/media.md).

---

## 6. Operational follow-ups

| Task | When | Why |
| --- | --- | --- |
| Monthly partition-creation job | Before month 24 | Keeps rows out of the default partition, so new partitions can still be attached |
| Detach partitions older than 24 months | Ongoing | Retention; keeps the table small |
| Orphan media cleanup (`pending` assets past the upload TTL) | With the first worker |
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
