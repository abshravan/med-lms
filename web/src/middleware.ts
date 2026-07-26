import { NextResponse, type NextRequest } from "next/server";

/**
 * Route-gating middleware.
 *
 * **This is a redirect optimisation, not a security boundary.** Read that twice
 * before extending it.
 *
 * Middleware runs on the Edge runtime, where the `pg` driver and Better Auth's
 * Node crypto are unavailable — so it cannot validate a session, only observe
 * that a session cookie is *present*. A forged or expired cookie passes this
 * check. Its only job is to avoid rendering a protected page's shell before
 * bouncing the user to sign-in.
 *
 * Authorisation is enforced in two places that genuinely can enforce it:
 *
 * 1. `src/app/(app)/layout.tsx` calls `auth.api.getSession()` on the server and
 *    redirects if there is no valid session.
 * 2. FastAPI verifies the access-token signature on every domain request.
 *
 * Anything sensitive is behind (2). Treating middleware as the gate is how
 * applications end up with an "authenticated" page that renders for anybody who
 * sets a cookie by hand.
 */

/** Requires a session. Prefix match. */
const PROTECTED_PREFIXES = ["/dashboard", "/courses", "/profile", "/admin"] as const;

/** Signed-in users are bounced away from these. */
const AUTH_ROUTES = [
  "/login",
  "/register",
  "/forgot-password",
] as const;

/**
 * Better Auth session cookie name.
 *
 * Derived from `advanced.cookiePrefix` in lib/auth/server.ts. The `__Secure-`
 * prefix is added by Better Auth when secure cookies are enabled, so both spellings
 * are checked rather than depending on NODE_ENV agreeing across runtimes.
 */
const SESSION_COOKIE_NAMES = [
  "medlms.session_token",
  "__Secure-medlms.session_token",
] as const;

function hasSessionCookie(request: NextRequest): boolean {
  return SESSION_COOKIE_NAMES.some((name) => {
    const cookie = request.cookies.get(name);
    return cookie !== undefined && cookie.value.length > 0;
  });
}

function isProtected(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isAuthRoute(pathname: string): boolean {
  return AUTH_ROUTES.some((route) => pathname === route);
}

/**
 * Validate a post-login redirect target.
 *
 * Only same-origin, absolute paths are allowed. Without this check, a link like
 * `/login?next=https://evil.example` turns the sign-in page into an open redirect
 * that phishes users with a legitimate-looking domain. `//evil.example` is
 * rejected too — browsers read it as protocol-relative and it would leave the site.
 */
function safeRedirectTarget(value: string | null): string | null {
  if (value === null || value.length === 0) {
    return null;
  }
  if (!value.startsWith("/") || value.startsWith("//")) {
    return null;
  }
  return value;
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  const authenticated = hasSessionCookie(request);

  if (isProtected(pathname) && !authenticated) {
    const loginUrl = new URL("/login", request.url);
    // Preserve the destination so sign-in returns the user where they were going.
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  if (isAuthRoute(pathname) && authenticated) {
    const requested = safeRedirectTarget(request.nextUrl.searchParams.get("next"));
    return NextResponse.redirect(new URL(requested ?? "/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Excludes `/api` (the auth handler manages its own access control), Next's
   * static output, and common static assets. Matching those would add latency to
   * every asset request for no benefit.
   */
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
