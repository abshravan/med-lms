"use client";

import { Eye, EyeOff } from "lucide-react";
import * as React from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { estimatePasswordStrength } from "@/features/auth/schemas";

export interface PasswordFieldProps {
  label: string;
  name: string;
  error?: string | undefined;
  hint?: string | undefined;
  autoComplete?: string | undefined;
  disabled?: boolean | undefined;
  placeholder?: string | undefined;
  registration?: UseFormRegisterReturn | undefined;
  /** Renders a strength meter. Only useful when choosing a new password. */
  showStrength?: boolean | undefined;
  /** Current value, required for the strength meter to react as the user types. */
  value?: string | undefined;
}

/**
 * A password input with a visibility toggle and an optional strength meter.
 *
 * The visibility toggle exists because a 12-character minimum without one causes
 * typos and abandoned sign-ups. It is a `button` with an accessible label, not an
 * icon-only div, and it never changes the input's `name` so form state is
 * untouched by toggling.
 *
 * The meter is advisory: it reports on what was typed and never blocks
 * submission. Zod already enforces the actual rule.
 */
export function PasswordField({
  label,
  name,
  error,
  hint,
  autoComplete,
  disabled,
  placeholder,
  registration,
  showStrength = false,
  value = "",
}: PasswordFieldProps) {
  const [visible, setVisible] = React.useState(false);
  const errorId = `${name}-error`;
  const hintId = `${name}-hint`;
  const strengthId = `${name}-strength`;
  const hasError = error !== undefined && error.length > 0;
  const showHint = !hasError && hint !== undefined && hint.length > 0;

  const strength = showStrength ? estimatePasswordStrength(value) : null;

  const describedBy =
    [
      hasError ? errorId : null,
      showHint ? hintId : null,
      strength !== null && strength.label.length > 0 ? strengthId : null,
    ]
      .filter((id): id is string => id !== null)
      .join(" ") || undefined;

  return (
    <div className="space-y-2">
      <Label htmlFor={name}>{label}</Label>

      <div className="relative">
        <Input
          id={name}
          type={visible ? "text" : "password"}
          autoComplete={autoComplete}
          disabled={disabled}
          placeholder={placeholder}
          aria-invalid={hasError}
          aria-describedby={describedBy}
          className="pr-10"
          {...registration}
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          // Excluded from the tab order: it is a convenience, and tabbing from the
          // password field should reach the submit button, not this.
          tabIndex={-1}
          className="absolute right-0 top-0 flex h-10 w-10 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
          // The field's label is included because a form can carry more than one
          // password field (sign-up, reset). Without it, a screen-reader user
          // browsing by button hears "Show password" twice with no way to tell
          // which field each one controls.
          aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
        >
          {visible ? (
            <EyeOff className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Eye className="h-4 w-4" aria-hidden="true" />
          )}
        </button>
      </div>

      {strength !== null && strength.label.length > 0 ? (
        <div className="space-y-1">
          <div className="flex gap-1" aria-hidden="true">
            {[0, 1, 2, 3].map((index) => (
              <div
                key={index}
                className={cn(
                  "h-1 flex-1 rounded-full transition-colors",
                  index < strength.score
                    ? strength.score <= 1
                      ? "bg-destructive"
                      : strength.score === 2
                        ? "bg-amber-500"
                        : "bg-emerald-500"
                    : "bg-muted",
                )}
              />
            ))}
          </div>
          <p id={strengthId} className="text-xs text-muted-foreground">
            Password strength: {strength.label}
          </p>
        </div>
      ) : null}

      {hasError ? (
        <p id={errorId} role="alert" className="text-sm font-medium text-destructive">
          {error}
        </p>
      ) : null}
      {showHint ? (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
