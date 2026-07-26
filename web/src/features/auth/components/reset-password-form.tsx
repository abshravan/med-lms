"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";

import { PasswordField } from "@/components/common/password-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  PASSWORD_MIN_LENGTH,
  resetPasswordSchema,
  type ResetPasswordInput,
} from "@/features/auth/schemas";
import { authClient } from "@/lib/auth/client";

export interface ResetPasswordFormProps {
  /** Single-use token from the emailed link. */
  token: string | null;
}

/**
 * Set a new password from a reset link.
 *
 * A missing or already-used token is handled as a first-class UI state rather than
 * an error banner on a form the user cannot submit — arriving here with a stale
 * link is common (links get forwarded, opened twice, or expire), and the useful
 * response is a path to request a fresh one.
 *
 * On success, Better Auth invalidates every other session for the account, so a
 * reset also evicts an attacker who was already signed in.
 */
export function ResetPasswordForm({ token }: ResetPasswordFormProps) {
  const router = useRouter();
  const [formError, setFormError] = React.useState<string | null>(null);
  const [succeeded, setSucceeded] = React.useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordInput>({
    resolver: zodResolver(resetPasswordSchema),
    mode: "onBlur",
    defaultValues: { password: "", confirmPassword: "" },
  });

  const password = watch("password");

  const onSubmit = handleSubmit(async (values) => {
    if (token === null) {
      return;
    }
    setFormError(null);

    const { error } = await authClient.resetPassword({
      newPassword: values.password,
      token,
    });

    if (error !== null && error !== undefined) {
      setFormError(
        "That reset link is no longer valid. Request a new one and try again.",
      );
      return;
    }

    setSucceeded(true);
    // A short pause so the confirmation is actually read before redirecting.
    setTimeout(() => {
      router.replace("/login");
    }, 2500);
  });

  if (token === null) {
    return (
      <div className="space-y-5">
        <Alert variant="destructive" title="This link is not valid">
          The reset link is missing or incomplete. Reset links expire after one hour
          and can only be used once.
        </Alert>
        <Button asChild className="w-full">
          <Link href="/forgot-password">Request a new link</Link>
        </Button>
      </div>
    );
  }

  if (succeeded) {
    return (
      <div className="space-y-5">
        <Alert variant="success" title="Password updated">
          You have been signed out everywhere else. Taking you to sign in…
        </Alert>
        <Button asChild variant="outline" className="w-full">
          <Link href="/login">Go to sign in now</Link>
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      {formError !== null ? (
        <Alert variant="destructive">
          {formError}{" "}
          <Link href="/forgot-password" className="font-medium underline">
            Request a new link
          </Link>
          .
        </Alert>
      ) : null}

      <PasswordField
        label="New password"
        name="password"
        autoComplete="new-password"
        disabled={isSubmitting}
        error={errors.password?.message}
        hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
        registration={register("password")}
        showStrength
        value={password}
      />

      <PasswordField
        label="Confirm new password"
        name="confirmPassword"
        autoComplete="new-password"
        disabled={isSubmitting}
        error={errors.confirmPassword?.message}
        registration={register("confirmPassword")}
      />

      <Button type="submit" className="w-full" loading={isSubmitting}>
        {isSubmitting ? "Updating…" : "Update password"}
      </Button>
    </form>
  );
}
