"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import * as React from "react";
import { useForm } from "react-hook-form";

import { TextField } from "@/components/common/text-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  forgotPasswordSchema,
  type ForgotPasswordInput,
} from "@/features/auth/schemas";
import { authClient } from "@/lib/auth/client";

/**
 * Password-reset request.
 *
 * **The response is identical whether or not the address exists.** This is the
 * whole security design of the screen: any difference in message, or even in
 * response time, tells an attacker which addresses are registered. So a success
 * state is shown unconditionally, and a genuine provider error is reported as a
 * generic failure rather than as "no such user".
 */
export function ForgotPasswordForm() {
  const [submitted, setSubmitted] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<ForgotPasswordInput>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);

    const { error } = await authClient.requestPasswordReset({
      email: values.email,
      redirectTo: "/reset-password",
    });

    // Only an infrastructure-level failure is surfaced. A "user not found" from
    // the provider is intentionally swallowed into the success state.
    if (error !== null && error !== undefined && error.status !== undefined && error.status >= 500) {
      setFormError("We could not process that request. Please try again shortly.");
      return;
    }

    setSubmitted(true);
  });

  if (submitted) {
    return (
      <div className="space-y-5">
        <Alert variant="success" title="Check your inbox">
          If an account exists for <strong>{getValues("email")}</strong>, we have sent a
          link to reset the password. It expires in one hour.
        </Alert>
        <p className="text-sm text-muted-foreground">
          Nothing arrived? Check your spam folder, or{" "}
          <button
            type="button"
            onClick={() => setSubmitted(false)}
            className="font-medium text-primary hover:underline"
          >
            try a different address
          </button>
          .
        </p>
        <Button asChild variant="outline" className="w-full">
          <Link href="/login">Back to sign in</Link>
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      {formError !== null ? <Alert variant="destructive">{formError}</Alert> : null}

      <TextField
        label="Email address"
        name="email"
        type="email"
        autoComplete="email"
        placeholder="you@medschool.edu"
        disabled={isSubmitting}
        error={errors.email?.message}
        registration={register("email")}
        autoFocus
      />

      <Button type="submit" className="w-full" loading={isSubmitting}>
        {isSubmitting ? "Sending…" : "Send reset link"}
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        <Link href="/login" className="font-medium text-primary hover:underline">
          Back to sign in
        </Link>
      </p>
    </form>
  );
}
