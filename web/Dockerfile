# Multi-stage build for the Next.js web application.

FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /app

# ── dependencies ─────────────────────────────────────────────────────────────
# Separated so a source change does not re-run the install.
FROM base AS deps
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ── development ──────────────────────────────────────────────────────────────
FROM base AS development
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["pnpm", "dev"]

# ── build ────────────────────────────────────────────────────────────────────
FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so they
# must be present here — unlike server-side variables, they cannot be supplied at
# runtime. They are public by definition; no secret may ever be passed this way.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_APP_URL=http://localhost:3000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN pnpm build

# ── production ───────────────────────────────────────────────────────────────
FROM base AS production

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup -g 10001 -S nodejs && adduser -u 10001 -S nextjs -G nodejs

# `output: "standalone"` emits a self-contained server with only the modules it
# actually uses — a far smaller image than copying all of node_modules.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/api/auth/jwks').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
