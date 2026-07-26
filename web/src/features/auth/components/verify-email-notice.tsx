"use client";

import Link from "next/link";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useResendVerification } from "@/features/auth/hooks/use-auth-actions";

export interface VerifyEmailNoticeProps {
  /** From the server session — never from a query parameter. */
  email: string | null;
  justSent: boolean;
  failed: boolean;
}

/**
 * Verification prompt with a resend action.
 *
 * The resend button is rate-limited server-side by Better Auth. Client-side it is
 * additionally put on a cooldown after each attempt, which prevents a frustrated
 * user from firing ten requests and then hitting the rate limit — a worse
 * experience than simply being asked to wait.
 */
export function VerifyEmailNotice({ email, justSent, failed }: VerifyEmailNoticeProps) {
  const { resend, isSending } = useResendVerification();
  const [result, setResult] = React.useState<{ ok: boolean; message: string } | null>(
    null,
  );
  const [cooldown, setCooldown] = React.useState(0);

  React.useEffect(() => {
    if (cooldown <= 0) {
      return;
    }
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const onResend = async () => {
    if (email === null) {
      return;
    }
    const outcome = await resend(email);
    setResult(outcome);
    if (outcome.ok) {
      setCooldown(60);
    }
  };

  return (
    <div className="space-y-5">
      {failed ? (
        <Alert variant="destructive" title="That link did not work">
          Verification links expire after one hour and can only be used once. Send
          yourself a fresh one below.
        </Alert>
      ) : justSent ? (
        <Alert variant="success" title="Account created">
          {email !== null ? (
            <>
              We sent a verification link to <strong>{email}</strong>. Open it to
              activate your account.
            </>
          ) : (
            <>We sent you a verification link. Open it to activate your account.</>
          )}
        </Alert>
      ) : (
        <Alert variant="info" title="Verification required">
          {email !== null ? (
            <>
              Your email address <strong>{email}</strong> is not verified yet.
            </>
          ) : (
            <>Your email address is not verified yet.</>
          )}
        </Alert>
      )}

      {result !== null ? (
        <Alert variant={result.ok ? "success" : "destructive"}>{result.message}</Alert>
      ) : null}

      {email !== null ? (
        <Button
          onClick={onResend}
          loading={isSending}
          disabled={cooldown > 0}
          variant="outline"
          className="w-full"
        >
          {cooldown > 0
            ? `Resend available in ${cooldown}s`
            : isSending
              ? "Sending…"
              : "Resend verification email"}
        </Button>
      ) : (
        <Button asChild className="w-full">
          <Link href="/login">Sign in to resend</Link>
        </Button>
      )}

      <p className="text-center text-sm text-muted-foreground">
        Already verified?{" "}
        <Link href="/dashboard" className="font-medium text-primary hover:underline">
          Go to your dashboard
        </Link>
      </p>
    </div>
  );
}
