"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";

import { PasswordField } from "@/components/common/password-field";
import { TextField } from "@/components/common/text-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { signInSchema, type SignInInput } from "@/features/auth/schemas";
import { authClient } from "@/lib/auth/client";
import { clearCachedAccessToken } from "@/lib/api/client";

export interface LoginFormProps {
  /** Where to go after a successful sign-in. Validated by the caller. */
  redirectTo?: string;
}

/**
 * Email + password sign-in.
 *
 * Error handling note: a failed sign-in always reports the same generic message
 * regardless of whether the email exists or the password was wrong. Distinguishing
 * them turns the form into an account-enumeration oracle — an attacker could
 * discover which addresses are registered on a medical-education platform, which
 * is itself sensitive.
 */
export function LoginForm({ redirectTo = "/dashboard" }: LoginFormProps) {
  const router = useRouter();
  const [formError, setFormError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SignInInput>({
    resolver: zodResolver(signInSchema),
    defaultValues: { email: "", password: "", rememberMe: true },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);

    // A stale token from a previous user must not survive into this session.
    clearCachedAccessToken();

    const { error } = await authClient.signIn.email({
      email: values.email,
      password: values.password,
      rememberMe: values.rememberMe,
    });

    if (error !== null && error !== undefined) {
      setFormError(
        error.status === 403
          ? "This account has been suspended. Please contact support."
          : "That email address and password do not match an account.",
      );
      return;
    }

    // `refresh` re-runs the server components so the layout picks up the new
    // session; `replace` keeps the login page out of the back-button history.
    router.replace(redirectTo);
    router.refresh();
  });

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
        // Sign-in is the first field a returning user needs.
        autoFocus
      />

      <PasswordField
        label="Password"
        name="password"
        autoComplete="current-password"
        disabled={isSubmitting}
        error={errors.password?.message}
        registration={register("password")}
      />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Checkbox id="rememberMe" disabled={isSubmitting} {...register("rememberMe")} />
          <Label htmlFor="rememberMe" className="cursor-pointer font-normal">
            Keep me signed in
          </Label>
        </div>
        <Link
          href="/forgot-password"
          className="text-sm font-medium text-primary hover:underline"
        >
          Forgot password?
        </Link>
      </div>

      <Button type="submit" className="w-full" loading={isSubmitting}>
        {isSubmitting ? "Signing in…" : "Sign in"}
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        New to MedLMS?{" "}
        <Link href="/register" className="font-medium text-primary hover:underline">
          Create an account
        </Link>
      </p>
    </form>
  );
}
