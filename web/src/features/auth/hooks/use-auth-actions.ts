"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import * as React from "react";

import { revokeCurrentSession } from "@/features/auth/api";
import { authKeys } from "@/features/auth/hooks/use-profile";
import { clearCachedAccessToken } from "@/lib/api/client";
import { authClient } from "@/lib/auth/client";

/**
 * Sign-out, done correctly.
 *
 * Three things must happen, in this order, and getting the order wrong leaves a
 * usable credential behind:
 *
 * 1. Ask the API to deny-list the outstanding access token. This must come first,
 *    while the session is still valid enough to authenticate the request.
 * 2. Destroy the Better Auth session (clears the cookie, deletes the row).
 * 3. Drop the in-memory token and the client cache.
 *
 * Step 1 is best-effort: if the API is unreachable we still complete sign-out
 * locally, because refusing to sign a user out is worse than a token that remains
 * technically valid for its remaining few minutes.
 */
export function useSignOut(): {
  signOut: () => Promise<void>;
  isSigningOut: boolean;
} {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [isSigningOut, setIsSigningOut] = React.useState(false);

  const signOut = React.useCallback(async () => {
    setIsSigningOut(true);
    try {
      try {
        await revokeCurrentSession();
      } catch {
        // Best-effort — see the note above.
      }

      await authClient.signOut();

      clearCachedAccessToken();
      queryClient.removeQueries({ queryKey: authKeys.all });

      router.replace("/login");
    } finally {
      setIsSigningOut(false);
    }
  }, [queryClient, router]);

  return { signOut, isSigningOut };
}

/**
 * Request a fresh verification email.
 *
 * Returns a discriminated result rather than throwing, because a failure here is
 * an expected UI state ("we couldn't send that, try again"), not an exception.
 */
export function useResendVerification(): {
  resend: (email: string) => Promise<{ ok: boolean; message: string }>;
  isSending: boolean;
} {
  const [isSending, setIsSending] = React.useState(false);

  const resend = React.useCallback(
    async (email: string): Promise<{ ok: boolean; message: string }> => {
      setIsSending(true);
      try {
        const { error } = await authClient.sendVerificationEmail({
          email,
          callbackURL: "/dashboard",
        });

        if (error !== null && error !== undefined) {
          return {
            ok: false,
            message: error.message ?? "We could not send the email. Please try again.",
          };
        }
        return {
          ok: true,
          message: "Verification email sent. Check your inbox.",
        };
      } finally {
        setIsSending(false);
      }
    },
    [],
  );

  return { resend, isSending };
}
