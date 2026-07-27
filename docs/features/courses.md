# Feature 2 — Courses & Lessons

Status: **complete**. Backend, frontend, validation, error handling, loading
states, tests, and documentation all shipped.

---

## 1. Scope

| Capability | Persona |
| --- | --- |
| Browse a searchable, filterable, paginated catalogue | Student |
| View a course landing page with its full outline | Student |
| Open a lesson (metadata; payload arrives in Features 3–4) | Student |
| Create, edit, publish, and archive courses | Admin |
| Add, edit, delete, and reorder modules and lessons | Admin |

**Deliberately out of scope.** Enrolment is deferred to the progress feature: it
is a student↔course relationship that only becomes meaningful once there is
progress to track, and adding it here would have meant a table with no readers.
Video payloads (Feature 3) and lesson notes (Feature 4) are likewise absent —
lessons carry `content_type` and `duration_seconds` so the catalogue can render
the right affordance, and the lesson page shows an explicit placeholder rather
than a blank area that reads as a bug.

**Authoring is API-only.** A bulk importer would land records as drafts and needs
no schema change, so designing for it now would only have meant weakening
constraints permanently.

---

## 2. Data model

```
courses ──1:N──> modules ──1:N──> lessons
   └──────────────────────────────────┘
        (denormalised course_id,
         kept honest by a composite FK)
```

### The two structural guarantees

Both are enforced by Postgres, not by application code, because application code
is what changes.

**1. A lesson's course cannot disagree with its module's course.**
`lessons.course_id` is denormalised so lesson lookups — and the future progress,
bookmark, and quiz tables — can filter by course without a join. Denormalisation
normally invites drift, so this one is made impossible to get wrong:

```sql
FOREIGN KEY (module_id, course_id) REFERENCES modules(id, course_id)
```

Moving a module between courses, or writing a lesson with the wrong `course_id`,
is rejected by the database. The convenience is kept; the drift risk is removed.

**2. Reordering is atomic.**
`UNIQUE (course_id, position)` and `UNIQUE (module_id, position)` are both
`DEFERRABLE INITIALLY DEFERRED`. A reorder rewrites every position in one
transaction; without deferral it would fail the instant two rows briefly shared a
slot, and the only alternatives are sparse positions (which drift) or a temporary
negative-offset dance (which is a workaround for a solved problem).

### Ordering: options considered

| Approach | Verdict |
| --- | --- |
| **Contiguous integer `position` + deferrable unique** ✅ | Chosen. Simple, gapless, human-readable, trivially sortable in SQL. A rewrite touches at most a few dozen rows. |
| Sparse integers (10, 20, 30…) | Avoids rewrites, but gaps drift toward exhaustion and eventually need renumbering anyway — the cost is deferred, not removed. |
| Fractional / LexoRank ranking | Correct for collaborative editing at scale. Here it buys nothing: courses have tens of items, not thousands, and it makes "what is lesson 3?" a sort rather than a lookup. |
| Linked list (`previous_id`) | O(n) reads and a broken chain is unrecoverable. |

### Publication lifecycle

`draft → published → archived`, with `published_at` set on first publish and
preserved thereafter.

A check constraint (`ck_courses_published_has_timestamp`) makes a published
course without a timestamp impossible — that combination would break both the
catalogue's ordering and its pagination cursor.

Courses are **archived, never deleted**: progress records, bookmarks, and quiz
attempts will reference them, and deletion would either orphan or cascade away a
student's history. Modules and lessons *are* hard-deleted — they are
organisational containers with nothing pointing at them yet. That asymmetry is
deliberate and should be revisited when progress tracking lands.

---

## 3. Read-path decisions

### Counts are computed, not denormalised

`lesson_count` and `total_duration_seconds` come from an aggregate over published
lessons rather than counter columns on `courses`.

Counters would need maintaining on lesson insert, update, delete, publish, and
reorder — five call sites, and they drift silently the first time one is missed.
Course counts are in the hundreds, and the aggregate runs against
`ix_lessons_course_id_status`.

> **Revisit when:** the catalogue query appears in slow logs, or course count
> exceeds ~10,000. The fix is a counter column maintained by a trigger (not by
> application code, for the reason above).

### Cursor pagination, not offset

Keyset over `(published_at DESC, id DESC)`. Offset paging degrades on two axes:
Postgres scans and discards skipped rows, and rows shift under the reader as
content is published — so items get duplicated or missed mid-browse. The `id`
tiebreak makes the ordering total, so a page boundary between two courses
published in the same instant is still stable.

`limit + 1` rows are fetched to determine `has_more`, avoiding a `COUNT(*)` over
the whole catalogue on every page request.

### No N+1

The course detail query uses `selectinload` at both levels — three queries total,
regardless of module or lesson count. A join would multiply rows cartesian-style
across modules × lessons.

The published-lesson filter lives **inside the loader**, not in application code,
so an unpublished lesson is never loaded into memory and cannot leak through a
serialisation mistake.

### Search

`ILIKE '%term%'` across title, subtitle, and specialty. A leading wildcard cannot
use a btree index, which is fine at catalogue scale.

> **Revisit when:** search latency becomes noticeable. The upgrade is a
> `tsvector` column with a GIN index, or Postgres trigram indexes for fuzzy
> matching.

---

## 4. API design notes

### Reordering replaces the whole set

`PUT /admin/courses/{id}/module-order` takes **every** module id in the desired
order, rather than a "move item X to index N" operation.

- Idempotent — replaying it is harmless.
- Cannot produce gaps or duplicates by construction.
- Two admins reordering concurrently resolve to last-write-wins *coherently*,
  rather than to an interleaved mess.
- The service rejects any list that is not exactly the current membership, so a
  partial list cannot silently relocate the omitted items and a foreign id
  cannot drag content in from another course.

### Draft content is 404, never 403

A `403` confirms that something exists. Every unpublished-content path returns
`NOT_FOUND`, so the endpoints cannot be used to probe for unreleased courses.

### `status` is absent from the create and update schemas

Publishing runs checks (at least one lesson). A writable `status` field would be
a way around them, so the lifecycle moves only through
`/publish` and `/archive`. With `extra="forbid"`, an attempt fails validation
before any logic runs.

### Slugs are validated, never auto-corrected

Omitting a slug derives one from the title (with `-2`, `-3` … on collision).
Supplying one that is not already URL-safe is a **422 with the corrected form in
the message** rather than a silent rewrite — a slug quietly changed underneath an
author makes the resulting URL a surprise.

A published course's slug is immutable. Renaming a live URL breaks every bookmark
and inbound link; if that is ever genuinely needed it should be a redirect table,
not a rename.

Lesson slugs are unique **per course**, not globally — two courses may each have
an "introduction", and the URL is course-scoped anyway.

---

## 5. Frontend decisions

### Reordering uses buttons, not drag-and-drop

Drag-and-drop would need `dnd-kit` (~30 kB) *plus* a keyboard-accessible
fallback, because dragging is unusable with a keyboard or a screen reader — so
the accessible controls have to exist either way. Up/down buttons are
keyboard-operable by default, announce their action (`Move Foundations up`), and
do not conflict with touch scrolling.

> **Revisit when:** courses routinely exceed ~20 modules. Then add drag *on top
> of* the buttons, never instead of them.

### `useInfiniteQuery`, not page numbers

The API is cursor-based: there is no page *number* to hold, only "what comes
after this". Modelling it as numbered pages would mean inventing an index the
server does not have.

### Every state is rendered explicitly

Loading (skeletons matching the real layout, so nothing jumps), empty (with
different copy for "nothing published" vs "your filter matched nothing"), error
(with a retry offered **only** when `error.isRetryable`), and end-of-list ("That
is every course." rather than an inert button).

### Descriptions render as plain text

Author-supplied `description` is rendered as text, not HTML — rendering it as
markup would be a stored-XSS vector. Sanitised markdown arrives with the notes
feature.

---

## 6. Authorization

| Surface | Guard |
| --- | --- |
| `/api/v1/courses/*` | `VerifiedUserDep` — authenticated **and** email-verified |
| `/api/v1/admin/*` | `require_role(ADMIN)`, declared **once on the router** |
| `/admin/*` pages | Server-side session role check in the layout |

The admin guard is declared on the router rather than per-route, so a new
endpoint cannot ship unprotected by forgetting a decorator — the standard failure
mode of per-route guards.

The role is read from **Postgres**, not the token claim, so a demoted admin loses
access immediately rather than at the end of the token's 15-minute life.

> **Deliberate gap:** admin routes require the admin role but *not* a verified
> email. The role itself is granted out-of-band (a manual SQL update by someone
> who already trusts the account), so verification would add ceremony without
> adding a trust decision — and it would block bootstrapping the first admin.
> Revisit if self-service admin invitations are ever added.

---

## 7. Verified end-to-end

Against real PostgreSQL 16 and real Next.js + FastAPI servers:

| # | Check | Result |
| --- | --- | --- |
| 1 | Create course as admin | `201`, `draft`, slug `clinical-cardiology` derived from `"Clinical Cardiology!"` |
| 2 | Add module + 3 lessons | slugs `cardiac-anatomy`, `the-ecg`, `heart-failure` |
| 3 | Catalogue while draft | `0` items — invisible to students |
| 4 | Unverified student hits catalogue | `403 EMAIL_NOT_VERIFIED` |
| 5 | Publish | `published`, cascaded to all 3 lessons |
| 6 | Catalogue after publish | 1 item, `lesson_count: 3`, `total_duration_seconds: 2700` |
| 7 | Reorder lessons (reversed) | positions `[0,1,2]`, outline reflects new order |
| 8 | Rename published slug | `409 CONFLICT` |
| 9 | Partial reorder list | `422` — "2 lesson(s) missing, 0 not recognised." |

---

## 8. Test coverage

| Suite | Count | Focus |
| --- | --- | --- |
| `tests/unit/test_slug_and_pagination.py` | 25 | Slug edge cases, cursor round-trip, limit clamping |
| `tests/integration/test_courses.py` | 20 | Catalogue reads, filters, pagination, visibility rules |
| `tests/integration/test_admin_courses.py` | 28 | Lifecycle, ordering, authorization, schema guarantees |
| `web/tests/course-schemas.test.ts` | 37 | Validation, duration conversion and formatting |
| `web/tests/course-catalogue.test.tsx` | 10 | Loading / results / empty / error / pagination states |
| **Feature 2 total** | **120** | |
| **Project total** | **231** (120 backend, 111 web) | |

Two tests assert directly against Postgres rather than through the API — the
composite foreign key and the published-timestamp check constraint. Those
protect against bugs in *future* application code that the service layer cannot
anticipate, so testing them through the service would miss the point.

Quality gates: `ruff` clean, `mypy --strict` clean (38 files), `tsc --noEmit`
clean, `next build` succeeds (15 routes).

---

## 9. Three defects found and fixed

**Alembic autogenerate emitted `DROP TABLE` for every audit-log partition.**
Partitions exist in Postgres but never in the model metadata, so autogenerate saw
24 unknown tables and proposed removing them. Applying that migration would have
destroyed the audit history the partitioning exists to preserve. `include_object`
now excludes partition children, discovered via `pg_inherits`.

**A migration that reported success and silently did nothing.** The partition
lookup above issues a `SELECT` before Alembic takes over the connection, which
opens an implicit transaction. SQLAlchemy rolled that transaction back on close —
discarding every DDL statement — while Alembic still logged `Running upgrade …`
and exited `0`. The commit is now explicit, with a comment explaining why it is
load-bearing rather than defensive.

**`formatDuration(45)` returned `"1m"`.** `Math.round(45/60)` is `1`, so the
seconds branch was unreachable for anything above 30 seconds. Now sub-minute
durations are checked first, and rounding to whole minutes before splitting makes
3599s read as `"1h"` rather than `"60m"`.

Also fixed: `slugify` discarded a trailing word that fitted the length limit
exactly, and query-parameter models validated by hand raised Pydantic's error
directly — escaping as a `500` instead of a `422`.

---

## 10. Known technical debt

| Item | Impact | Trigger |
| --- | --- | --- |
| **API types hand-mirrored in TypeScript** | Contract can drift between languages | **Now overdue** — adopt `openapi-typescript` before Feature 3 |
| `ILIKE` search cannot use an index | Slow search as the catalogue grows | Noticeable latency → `tsvector` + GIN |
| Counts computed per request | Extra aggregate per catalogue page | >10k courses → trigger-maintained counters |
| Modules/lessons hard-deleted | Deleting a lesson will orphan progress rows | **Before the progress feature** — switch to soft delete |
| No cover-image upload | `cover_image_key` is always null | Feature 3 (media pipeline) |
| Module/lesson edit is create-and-delete only | No inline rename in the UI (API supports it) | First author complaint |
| Admin routes do not require email verification | See §6 | Self-service admin invitations |

---

## 11. What this feature leaves behind

- `courses`, `modules`, `lessons` — the tables every later feature hangs off.
  **Foreign-key to `lessons.id` and `courses.id`**, and to
  `user_profiles.user_id` for the student side.
- Cursor pagination (`utils/pagination.py`) and slug generation
  (`utils/slug.py`), both generic and tested.
- `Page<T>` / `PaginationMeta` in the response envelope, ready for any list.
- `SelectField`, `TextareaField`, `Badge`, `Select`, `Textarea` — the form and
  display vocabulary.
- A proven whole-set reorder pattern, for quiz questions and flashcard decks.
