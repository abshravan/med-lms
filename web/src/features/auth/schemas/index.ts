/**
 * Auth validation schemas.
 *
 * Single source of truth for auth input rules. `react-hook-form` resolves these
 * for instant client-side feedback, and the same constants configure Better Auth
 * on the server — so the two cannot disagree about what a valid password is.
 *
 * Client validation is a UX affordance, never a security control: Better Auth and
 * FastAPI both re-validate. Rule 14 — validation is never skipped — holds because
 * the server does not trust any of this.
 */

import { z } from "zod";

/** Must match `minPasswordLength` in lib/auth/server.ts. */
export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 128;
export const NAME_MAX_LENGTH = 120;

/**
 * Email rule.
 *
 * Lower-cased and trimmed so `Ada@Med.test` and `ada@med.test` cannot become two
 * accounts. Length is capped at 320 — the RFC maximum — to bound what reaches
 * the database and the mail provider.
 */
export const emailSchema = z
  .string()
  .trim()
  .min(1, "Email address is required")
  .max(320, "That email address is too long")
  .email("Enter a valid email address")
  .toLowerCase();

/**
 * Password rule.
 *
 * Length-first: 12 characters minimum, with no composition requirements. Forced
 * symbol/digit rules measurably push users toward predictable patterns
 * (`Password1!`) without adding real entropy. The one extra check is a rejection
 * of a handful of obviously-common passwords, which is cheap and catches the
 * worst choices.
 */
export const passwordSchema = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `Use at least ${PASSWORD_MIN_LENGTH} characters`)
  .max(PASSWORD_MAX_LENGTH, "That password is too long")
  .refine((value) => !COMMON_PASSWORDS.has(value.toLowerCase()), {
    message: "That password is too common — please choose another",
  });

/**
 * A short deny-list of passwords that clear the length rule but are still
 * terrible. Not a substitute for a real breach-corpus check (HaveIBeenPwned's
 * k-anonymity range API), which is the right follow-up.
 */
const COMMON_PASSWORDS = new Set([
  "password1234",
  "passwordpassword",
  "123456789012",
  "qwertyuiop12",
  "letmeinplease",
  "iloveyou1234",
  "administrator",
  "welcome12345",
]);

export const signInSchema = z.object({
  email: emailSchema,
  // Not `passwordSchema`: an existing account may predate a rule change, and
  // telling someone their *correct* password is invalid at sign-in is a dead end.
  password: z.string().min(1, "Password is required"),
  rememberMe: z.boolean().default(true),
});

export const signUpSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(2, "Enter your full name")
      .max(NAME_MAX_LENGTH, "That name is too long"),
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string().min(1, "Please confirm your password"),
    acceptedTerms: z.boolean().refine((value) => value, {
      message: "You must accept the terms to continue",
    }),
  })
  // Attached to `confirmPassword` so the message renders next to the field the
  // user needs to fix, rather than at the form level.
  .refine((values) => values.password === values.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

export const forgotPasswordSchema = z.object({
  email: emailSchema,
});

export const resetPasswordSchema = z
  .object({
    password: passwordSchema,
    confirmPassword: z.string().min(1, "Please confirm your password"),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

/**
 * Profile update.
 *
 * Mirrors `UserProfileUpdate` in backend/app/schemas/auth.py, including the
 * omissions: `email` and `role` are absent because changing them is not a profile
 * edit. The backend rejects them outright.
 */
export const profileUpdateSchema = z.object({
  display_name: z
    .string()
    .trim()
    .min(1, "Display name cannot be empty")
    .max(120, "That name is too long")
    .optional(),
  institution: z.string().trim().max(200, "That name is too long").optional(),
  year_of_study: z
    .number()
    .int("Enter a whole number")
    .min(1, "Year must be between 1 and 10")
    .max(10, "Year must be between 1 and 10")
    .optional(),
  specialization: z.string().trim().max(120, "That name is too long").optional(),
  timezone: z.string().trim().min(1).max(64).optional(),
  locale: z.string().trim().min(2).max(16).optional(),
});

export type SignInInput = z.infer<typeof signInSchema>;
export type SignUpInput = z.infer<typeof signUpSchema>;
export type ForgotPasswordInput = z.infer<typeof forgotPasswordSchema>;
export type ResetPasswordInput = z.infer<typeof resetPasswordSchema>;
export type ProfileUpdateInput = z.infer<typeof profileUpdateSchema>;

/**
 * A coarse password-strength signal for the meter in the sign-up form.
 *
 * Heuristic and advisory only — it never blocks submission. A real estimator
 * (zxcvbn) is ~800 kB, which is not a trade worth making on the critical
 * registration path.
 */
export function estimatePasswordStrength(password: string): {
  score: 0 | 1 | 2 | 3 | 4;
  label: string;
} {
  if (password.length === 0) {
    return { score: 0, label: "" };
  }

  let score = 0;
  if (password.length >= PASSWORD_MIN_LENGTH) score += 1;
  if (password.length >= 16) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password) && /[^\w\s]/.test(password)) score += 1;

  const clamped = Math.min(score, 4) as 0 | 1 | 2 | 3 | 4;
  const labels = ["Very weak", "Weak", "Fair", "Good", "Strong"] as const;
  return { score: clamped, label: labels[clamped] };
}
