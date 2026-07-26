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
import {
  PASSWORD_MIN_LENGTH,
  signUpSchema,
  type SignUpInput,
} from "@/features/auth/schemas";
import { authClient } from "@/lib/auth/client";

/**
 * Registration form.
 *
 * Note what is *not* here: no role selector. Role is assigned server-side and the
 * field is marked `input: false` in the Better Auth config, so a crafted request
 * cannot create an admin. A role picker on a public sign-up form is the most
 * common privilege-escalation bug in this kind of application.
 */
export function RegisterForm() {
  const router = useRouter();
  const [formError, setFormError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<SignUpInput>({
    resolver: zodResolver(signUpSchema),
    // Validate as the user leaves each field: immediate enough to be helpful,
    // without shouting about an incomplete password on the first keystroke.
    mode: "onBlur",
    defaultValues: {
      name: "",
      email: "",
      password: "",
      confirmPassword: "",
      acceptedTerms: false,
    },
  });

  // Watched so the strength meter updates live.
  const password = watch("password");

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);

    const { error } = await authClient.signUp.email({
      name: values.name,
      email: values.email,
      password: values.password,
      callbackURL: "/dashboard",
    });

    if (error !== null && error !== undefined) {
      // 422 from Better Auth means the address is already registered. The message
      // avoids confirming that outright while still being actionable.
      setFormError(
        error.status === 422 || error.status === 400
          ? "We could not create that account. If you already have one, try signing in."
          : "Something went wrong creating your account. Please try again.",
      );
      return;
    }

    router.push("/verify-email?sent=1");
  });

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      {formError !== null ? <Alert variant="destructive">{formError}</Alert> : null}

      <TextField
        label="Full name"
        name="name"
        autoComplete="name"
        placeholder="Ada Lovelace"
        disabled={isSubmitting}
        error={errors.name?.message}
        registration={register("name")}
        autoFocus
      />

      <TextField
        label="Email address"
        name="email"
        type="email"
        autoComplete="email"
        placeholder="you@medschool.edu"
        hint="Use your institutional address if you have one."
        disabled={isSubmitting}
        error={errors.email?.message}
        registration={register("email")}
      />

      <PasswordField
        label="Password"
        name="password"
        autoComplete="new-password"
        disabled={isSubmitting}
        error={errors.password?.message}
        hint={`At least ${PASSWORD_MIN_LENGTH} characters. A memorable phrase works well.`}
        registration={register("password")}
        showStrength
        value={password}
      />

      <PasswordField
        label="Confirm password"
        name="confirmPassword"
        autoComplete="new-password"
        disabled={isSubmitting}
        error={errors.confirmPassword?.message}
        registration={register("confirmPassword")}
      />

      <div className="space-y-2">
        <div className="flex items-start gap-2">
          <Checkbox
            id="acceptedTerms"
            className="mt-1"
            disabled={isSubmitting}
            aria-invalid={errors.acceptedTerms !== undefined}
            aria-describedby={
              errors.acceptedTerms !== undefined ? "acceptedTerms-error" : undefined
            }
            {...register("acceptedTerms")}
          />
          <Label htmlFor="acceptedTerms" className="cursor-pointer font-normal leading-relaxed">
            I agree to the{" "}
            <Link href="/terms" className="text-primary hover:underline">
              terms of service
            </Link>{" "}
            and{" "}
            <Link href="/privacy" className="text-primary hover:underline">
              privacy policy
            </Link>
            .
          </Label>
        </div>
        {errors.acceptedTerms !== undefined ? (
          <p
            id="acceptedTerms-error"
            role="alert"
            className="text-sm font-medium text-destructive"
          >
            {errors.acceptedTerms.message}
          </p>
        ) : null}
      </div>

      <Button type="submit" className="w-full" loading={isSubmitting}>
        {isSubmitting ? "Creating your account…" : "Create account"}
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
