/**
 * TanStack Query configuration.
 *
 * The retry policy is the interesting part. The default retries everything three
 * times, which is wrong for an authenticated API: retrying a 401 or a 403 cannot
 * succeed, and it delays the redirect to sign-in by several seconds while the user
 * stares at a spinner. Here, only genuinely transient failures are retried.
 */

import { QueryClient, type DefaultOptions } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";

const MAX_RETRIES = 2;

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES) {
    return false;
  }
  // Non-`ApiError` failures are programming errors, not transient ones.
  if (!(error instanceof ApiError)) {
    return false;
  }
  return error.isRetryable;
}

const defaultOptions: DefaultOptions = {
  queries: {
    // Long enough that navigating between pages does not refetch the profile,
    // short enough that a role or verification change appears promptly.
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    retry: shouldRetry,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    // The window regaining focus is not a reason to refetch everything; it causes
    // a request storm on tab-heavy usage.
    refetchOnWindowFocus: false,
    refetchOnReconnect: true,
  },
  mutations: {
    // Mutations are never retried automatically: without server-side idempotency
    // keys, a retried POST can duplicate an effect.
    retry: false,
  },
};

/** Create a client. One per browser session, or one per request on the server. */
export function createQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions });
}
