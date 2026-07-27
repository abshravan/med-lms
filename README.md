# MedLMS

A medical education platform: video lessons, lecture notes, downloadable PDFs,
progress tracking, bookmarks, AI-generated flashcards, quizzes, and AI-powered
voice viva practice — across web and mobile.

**Current status:** Authentication and the course catalogue are complete. The media pipeline is next.

---

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 15 · TypeScript · Tailwind CSS v4 · shadcn/ui · TanStack Query · React Hook Form · Zod |
| Backend | FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · Redis 7 |
| Identity | Better Auth (in Next.js), ES256 JWTs verified by FastAPI |
| Storage | Cloudflare R2 *(planned)* |
| Realtime | WebSocket · OpenAI Realtime / Gemini Live *(planned)* |
| Deployment | Docker · Docker Compose |

---

## Quick start

**Prerequisites:** Docker + Docker Compose. (For running outside Docker: Node 22
with pnpm, Python 3.11, PostgreSQL 16, Redis 7.)

```bash
git clone <repository-url> && cd med-lms
cp .env.example .env
```

Fill in the two required secrets — Compose refuses to start without them:

```bash
openssl rand -base64 32   # → BETTER_AUTH_SECRET
openssl rand -hex 16      # → POSTGRES_PASSWORD
```

Then bring up the datastores, migrate, and start everything:

```bash
docker compose up -d postgres redis
./scripts/migrate.sh
docker compose up
```

| Service | URL |
| --- | --- |
| Web | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs *(disabled in production)* |

Register at http://localhost:3000/register. With `RESEND_API_KEY` unset, the
verification email is printed to the web container's logs — so the full flow
works locally with no third-party account.

> **Migration order is not optional.** Better Auth owns the `auth` schema and
> must migrate before Alembic, which adds a foreign key into it. `scripts/migrate.sh`
> enforces the order; running Alembic first fails with a message naming the fix.

---

## Running without Docker

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # edit DATABASE_URL, REDIS_URL, AUTH_*
alembic upgrade head          # after the web migration below
uvicorn app.main:app --reload
```

**Web**

```bash
cd web
pnpm install
cp .env.example .env.local    # edit DATABASE_URL, BETTER_AUTH_SECRET
pnpm auth:bootstrap && pnpm auth:migrate
pnpm dev
```

---

## Tests and quality gates

```bash
# Backend — needs a PostgreSQL instance; set TEST_DATABASE_URL
cd backend
pytest                        # 120 tests
ruff check app tests alembic
mypy app                      # strict

# Web
cd web
pnpm test                     # 111 tests
pnpm typecheck
pnpm lint
```

Backend tests apply the **real Alembic migrations** and the **real Better Auth
DDL**, so a broken migration fails the suite rather than a deploy.

---

## Architecture in one paragraph

Two runtimes over one PostgreSQL database. **Next.js owns identity**: Better Auth
handles credentials, sessions, and verification, and mints 15-minute ES256 access
tokens. **FastAPI owns the domain**: it verifies those tokens *offline* against a
cached JWKS — no network call per request — and serves `/api/v1`. The database is
split into two schemas with two migration owners that never touch each other's
tables: `auth` (Better Auth CLI) and `public` (Alembic). Redis caches the JWKS and
holds a revocation deny-list so sign-out and bans take effect immediately rather
than at token expiry.

It is a modular monolith on each side, with hard module boundaries drawn where the
microservice seams will eventually be cut — media, AI/realtime, and analytics
first; core learning stays.

Full reasoning, tradeoffs, and scaling plan: **[docs/architecture.md](docs/architecture.md)**.

---

## Documentation

| Document | Contents |
| --- | --- |
| [architecture.md](docs/architecture.md) | System design, decisions and tradeoffs, video/AI/viva design, scaling, future service boundaries |
| [api.md](docs/api.md) | Endpoint reference, response envelope, error codes |
| [database.md](docs/database.md) | Schema, ER diagram, migration order, partitioning |
| [folder-tree.md](docs/folder-tree.md) | Directory layout and placement rules |
| [dependency-graph.md](docs/dependency-graph.md) | Module graph and package rationale |
| [features/authentication.md](docs/features/authentication.md) | Feature 1: what was built, security properties, known debt |
| [features/courses.md](docs/features/courses.md) | Feature 2: catalogue design, ordering, publication lifecycle |

---

## Project conventions

- **Every API response uses the same envelope** — `{ success, data, message }` —
  applied by the route layer, not by individual handlers, so a route cannot ship
  an unwrapped payload.
- **A feature never imports another feature.** Shared code moves down into
  `components/common`, `lib`, `hooks`, or `services`.
- **The ORM stays in the repository layer.** Services own transactions; routers
  own HTTP and nothing else.
- **No `any` in TypeScript.** `strict` plus `noUncheckedIndexedAccess`.
- **Validation is never skipped**, and the server never trusts the client's copy
  of it.
- **Secrets come only from the environment**, validated at boot; a missing secret
  fails the start rather than defaulting to something insecure.
- Adding a feature updates `api.md`, `database.md`, `folder-tree.md`, and
  `dependency-graph.md`.

---

## Roadmap

1. ~~Authentication~~ ✅
2. ~~Courses & lessons~~ ✅ — catalogue, modules, admin authoring
3. **Media pipeline** — R2 upload, HLS transcode, signed playback
4. Notes & PDFs
5. Progress tracking & bookmarks
6. AI flashcards
7. Quizzes
8. Voice viva (realtime)
9. Analytics
