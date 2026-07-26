-- Better Auth identity schema — REFERENCE COPY, NOT A MIGRATION.
--
-- Generated with:
--   cd web && pnpm auth:bootstrap && pnpm auth:migrate
--   pg_dump --schema=auth --schema-only --no-owner --no-privileges
--
-- Purpose:
--   1. Makes the identity schema reviewable in version control. A Better Auth
--      upgrade that changes a column becomes a visible diff in a pull request
--      instead of a silent production change.
--   2. Applied by the backend test suite so tests run against the real identity
--      DDL rather than an approximation of it.
--
-- This file is NOT the source of truth and must never be applied to production.
-- The `better-auth` CLI owns this schema (docs/architecture.md §5.1). Regenerate
-- this file whenever `pnpm auth:migrate` reports a change.
--
-- Generated from: better-auth 1.6.25

CREATE TABLE auth.account (
    id text NOT NULL,
    "accountId" text NOT NULL,
    "providerId" text NOT NULL,
    "userId" text NOT NULL,
    "accessToken" text,
    "refreshToken" text,
    "idToken" text,
    "accessTokenExpiresAt" timestamp with time zone,
    "refreshTokenExpiresAt" timestamp with time zone,
    scope text,
    password text,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone NOT NULL
);
CREATE TABLE auth.jwks (
    id text NOT NULL,
    "publicKey" text NOT NULL,
    "privateKey" text NOT NULL,
    "createdAt" timestamp with time zone NOT NULL,
    "expiresAt" timestamp with time zone
);
CREATE TABLE auth.session (
    id text NOT NULL,
    "expiresAt" timestamp with time zone NOT NULL,
    token text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone NOT NULL,
    "ipAddress" text,
    "userAgent" text,
    "userId" text NOT NULL,
    "impersonatedBy" text
);
CREATE TABLE auth."user" (
    id text NOT NULL,
    name text NOT NULL,
    email text NOT NULL,
    "emailVerified" boolean NOT NULL,
    image text,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    role text,
    banned boolean,
    "banReason" text,
    "banExpires" timestamp with time zone
);
CREATE TABLE auth.verification (
    id text NOT NULL,
    identifier text NOT NULL,
    value text NOT NULL,
    "expiresAt" timestamp with time zone NOT NULL,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);
ALTER TABLE ONLY auth.account
    ADD CONSTRAINT account_pkey PRIMARY KEY (id);
ALTER TABLE ONLY auth.jwks
    ADD CONSTRAINT jwks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY auth.session
    ADD CONSTRAINT session_pkey PRIMARY KEY (id);
ALTER TABLE ONLY auth.session
    ADD CONSTRAINT session_token_key UNIQUE (token);
ALTER TABLE ONLY auth."user"
    ADD CONSTRAINT user_email_key UNIQUE (email);
ALTER TABLE ONLY auth."user"
    ADD CONSTRAINT user_pkey PRIMARY KEY (id);
ALTER TABLE ONLY auth.verification
    ADD CONSTRAINT verification_pkey PRIMARY KEY (id);
CREATE INDEX "account_userId_idx" ON auth.account USING btree ("userId");
CREATE INDEX "session_userId_idx" ON auth.session USING btree ("userId");
CREATE INDEX verification_identifier_idx ON auth.verification USING btree (identifier);
ALTER TABLE ONLY auth.account
    ADD CONSTRAINT "account_userId_fkey" FOREIGN KEY ("userId") REFERENCES auth."user"(id) ON DELETE CASCADE;
ALTER TABLE ONLY auth.session
    ADD CONSTRAINT "session_userId_fkey" FOREIGN KEY ("userId") REFERENCES auth."user"(id) ON DELETE CASCADE;
