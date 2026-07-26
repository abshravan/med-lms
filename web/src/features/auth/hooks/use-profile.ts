"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { fetchProfile, updateProfile } from "@/features/auth/api";
import type { ProfileUpdateInput } from "@/features/auth/schemas";
import type { UserProfile } from "@/features/auth/types";
import { ApiError } from "@/lib/api/errors";

/**
 * Query keys as a const tree.
 *
 * A single exported structure rather than string literals scattered through
 * components: invalidating "everything auth" is then `authKeys.all`, and a typo in
 * a key becomes a type error instead of a cache miss that silently never
 * invalidates.
 */
export const authKeys = {
  all: ["auth"] as const,
  profile: () => [...authKeys.all, "profile"] as const,
  session: () => [...authKeys.all, "session"] as const,
} as const;

/** Fetch the authenticated user's profile. */
export function useProfile(
  options: { enabled?: boolean } = {},
): UseQueryResult<UserProfile, ApiError> {
  return useQuery<UserProfile, ApiError>({
    queryKey: authKeys.profile(),
    queryFn: ({ signal }) => fetchProfile(signal),
    enabled: options.enabled ?? true,
    // An unauthenticated user is a settled answer, not a transient failure — do
    // not keep retrying, just let the caller redirect.
    retry: (failureCount, error) =>
      !error.isAuthError && error.isRetryable && failureCount < 2,
  });
}

/**
 * Update the authenticated user's profile.
 *
 * The server response is written straight into the cache rather than triggering a
 * refetch, so the UI settles in one round-trip instead of two.
 *
 * Optimistic updates are deliberately not used here: this form is not
 * latency-sensitive, and rolling back an optimistic profile edit on a validation
 * failure produces a confusing flicker where the user's input reverts.
 */
export function useUpdateProfile(): UseMutationResult<
  UserProfile,
  ApiError,
  ProfileUpdateInput
> {
  const queryClient = useQueryClient();

  return useMutation<UserProfile, ApiError, ProfileUpdateInput>({
    mutationFn: updateProfile,
    onSuccess: (profile) => {
      queryClient.setQueryData(authKeys.profile(), profile);
    },
  });
}
