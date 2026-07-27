/**
 * Typed client for the FastAPI domain API.
 *
 * Responsibilities, all in one place so no feature has to reimplement them:
 *
 * 1. Attach a fresh access token, fetched from Better Auth on demand.
 * 2. Unwrap the response envelope, returning `data` and throwing `ApiError`.
 * 3. Refresh the token exactly once on a 401 and retry the request once.
 *
 * **Why tokens are held in memory and never in `localStorage`.** A token in
 * `localStorage` is readable by any script on the page, so a single XSS becomes a
 * stolen credential that outlives the page. Keeping it in a module-scoped variable
 * means it dies with the tab, and the durable credential remains the `httpOnly`
 * session cookie, which script cannot read at all.
 *
 * **Why retry is capped at one attempt.** A 401 after a fresh token means the
 * underlying session is gone, not that the token was stale. Retrying further
 * would spin — the correct response is to surface an auth error and let the
 * caller redirect to sign-in.
 */

import { ApiError } from "@/lib/api/errors";
import { clientEnv } from "@/lib/env";
import type { ApiResponse } from "@/types/api";

const REQUEST_ID_HEADER = "X-Request-ID";

/** Seconds before expiry at which a cached token is considered stale. */
const TOKEN_REFRESH_MARGIN_SECONDS = 60;

interface CachedToken {
  token: string;
  expiresAtMs: number;
}

let cachedToken: CachedToken | null = null;
/** Shared across concurrent callers so a page load does not mint N tokens. */
let inFlightTokenRequest: Promise<string | null> | null = null;

/** Discard the cached token. Called on sign-out and on a hard auth failure. */
export function clearCachedAccessToken(): void {
  cachedToken = null;
  inFlightTokenRequest = null;
}

/** Decode a JWT's `exp` without verifying it — the API does the verifying. */
function readExpiry(token: string): number | null {
  const segments = token.split(".");
  if (segments.length !== 3) {
    return null;
  }
  try {
    const payloadSegment = segments[1]!.replace(/-/g, "+").replace(/_/g, "/");
    const decoded: unknown = JSON.parse(atob(payloadSegment));
    if (
      typeof decoded === "object" &&
      decoded !== null &&
      "exp" in decoded &&
      typeof (decoded as { exp: unknown }).exp === "number"
    ) {
      return (decoded as { exp: number }).exp * 1000;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Fetch an access token from Better Auth.
 *
 * Same-origin and cookie-authenticated, so no credential is passed explicitly.
 * Returns null when there is no active session.
 */
async function fetchAccessToken(): Promise<string | null> {
  const response = await fetch("/api/auth/token", {
    method: "GET",
    credentials: "include",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    return null;
  }

  const body: unknown = await response.json().catch(() => null);
  if (
    typeof body === "object" &&
    body !== null &&
    "token" in body &&
    typeof (body as { token: unknown }).token === "string"
  ) {
    return (body as { token: string }).token;
  }
  return null;
}

/** Return a usable access token, from cache when possible. */
async function getAccessToken(forceRefresh = false): Promise<string | null> {
  const now = Date.now();

  if (
    !forceRefresh &&
    cachedToken !== null &&
    cachedToken.expiresAtMs - TOKEN_REFRESH_MARGIN_SECONDS * 1000 > now
  ) {
    return cachedToken.token;
  }

  if (forceRefresh) {
    cachedToken = null;
  }

  // Collapse concurrent refreshes into one network call.
  if (inFlightTokenRequest === null) {
    inFlightTokenRequest = fetchAccessToken().finally(() => {
      inFlightTokenRequest = null;
    });
  }

  const token = await inFlightTokenRequest;
  if (token === null) {
    return null;
  }

  const expiresAtMs = readExpiry(token);
  cachedToken = {
    token,
    // If `exp` is unreadable, assume a conservative short life rather than
    // caching a token indefinitely.
    expiresAtMs: expiresAtMs ?? now + 60_000,
  };
  return token;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  /** Serialised as JSON. Omit for GET. */
  body?: unknown;
  /** Requests without a token, for public endpoints. */
  skipAuth?: boolean;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

function buildUrl(path: string): string {
  const base = clientEnv.NEXT_PUBLIC_API_URL.replace(/\/$/, "");
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

/** Convert an envelope error body into an `ApiError`. */
function toApiError(
  body: ApiResponse<unknown> | null,
  status: number,
  requestId: string | null,
): ApiError {
  if (body !== null && body.success === false) {
    return new ApiError({
      message: body.message,
      code: body.error.code,
      status,
      fieldErrors: body.error.details ?? [],
      requestId: body.meta?.request_id ?? requestId,
    });
  }
  return ApiError.malformed(status, requestId);
}

async function performRequest<TData>(
  path: string,
  options: RequestOptions,
  token: string | null,
): Promise<{ data: TData } | { error: ApiError }> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...options.headers,
  };

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token !== null) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      method: options.method ?? "GET",
      headers,
      ...(options.body !== undefined
        ? { body: JSON.stringify(options.body) }
        : {}),
      ...(options.signal !== undefined ? { signal: options.signal } : {}),
    });
  } catch (cause) {
    // An aborted request is the caller's intent, not a failure to report.
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw cause;
    }
    return { error: ApiError.network(cause) };
  }

  const requestId = response.headers.get(REQUEST_ID_HEADER);

  // 204 has no body; nothing to unwrap.
  if (response.status === 204) {
    return { data: undefined as TData };
  }

  const body = (await response.json().catch(() => null)) as
    | ApiResponse<TData>
    | null;

  if (!response.ok || body === null || body.success === false) {
    return { error: toApiError(body, response.status, requestId) };
  }

  return { data: body.data };
}

/**
 * Call the domain API and return the unwrapped `data`.
 *
 * @throws {ApiError} On any failure other than an abort.
 */
export async function apiRequest<TData>(
  path: string,
  options: RequestOptions = {},
): Promise<TData> {
  const token = options.skipAuth === true ? null : await getAccessToken();

  if (options.skipAuth !== true && token === null) {
    clearCachedAccessToken();
    throw new ApiError({
      message: "You are not signed in.",
      code: "UNAUTHENTICATED",
      status: 401,
    });
  }

  const first = await performRequest<TData>(path, options, token);
  if ("data" in first) {
    return first.data;
  }

  // One retry with a freshly minted token — covers the ordinary case of a token
  // that expired between being cached and being used.
  const shouldRetry =
    options.skipAuth !== true &&
    (first.error.code === "TOKEN_EXPIRED" || first.error.code === "TOKEN_INVALID");

  if (!shouldRetry) {
    if (first.error.isAuthError) {
      clearCachedAccessToken();
    }
    throw first.error;
  }

  const refreshed = await getAccessToken(true);
  if (refreshed === null) {
    clearCachedAccessToken();
    throw new ApiError({
      message: "Your session has ended. Please sign in again.",
      code: "SESSION_REVOKED",
      status: 401,
    });
  }

  const second = await performRequest<TData>(path, options, refreshed);
  if ("data" in second) {
    return second.data;
  }

  if (second.error.isAuthError) {
    clearCachedAccessToken();
  }
  throw second.error;
}

/** Convenience wrappers. Thin on purpose — all logic lives in `apiRequest`. */
export const api = {
  get: <TData>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<TData>(path, { ...options, method: "GET" }),

  post: <TData>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => apiRequest<TData>(path, { ...options, method: "POST", body }),

  patch: <TData>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => apiRequest<TData>(path, { ...options, method: "PATCH", body }),

  put: <TData>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => apiRequest<TData>(path, { ...options, method: "PUT", body }),

  delete: <TData>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<TData>(path, { ...options, method: "DELETE" }),
};
