"use client";

import * as React from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { Input, type InputProps } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export interface TextFieldProps extends Omit<InputProps, "id" | "aria-invalid"> {
  /** Visible label. Always rendered — placeholders are not labels. */
  label: string;
  /** Field name; also the element id, so the label's `htmlFor` is correct. */
  name: string;
  /** Validation message. Presence flips the field into its invalid state. */
  error?: string | undefined;
  /** Guidance shown when there is no error. */
  hint?: string | undefined;
  /** Result of `register(name)` from react-hook-form. */
  registration?: UseFormRegisterReturn | undefined;
}

/**
 * A labelled text input with validation messaging and correct ARIA wiring.
 *
 * Every auth form uses this rather than assembling label + input + error itself.
 * That is not just less code: it means the accessibility contract is implemented
 * once and correctly, instead of eight times with subtle differences.
 *
 * - `aria-invalid` drives both the announcement and the styling.
 * - `aria-describedby` points at whichever of hint/error is currently rendered,
 *   so the message is read out with the field, not orphaned beside it.
 * - The error has `role="alert"` so it is announced the moment it appears.
 */
export const TextField = React.forwardRef<HTMLInputElement, TextFieldProps>(
  ({ label, name, error, hint, registration, className, ...props }, ref) => {
    const errorId = `${name}-error`;
    const hintId = `${name}-hint`;
    const hasError = error !== undefined && error.length > 0;
    const showHint = !hasError && hint !== undefined && hint.length > 0;

    return (
      <div className="space-y-2">
        <Label htmlFor={name}>{label}</Label>
        <Input
          id={name}
          ref={ref}
          aria-invalid={hasError}
          aria-describedby={hasError ? errorId : showHint ? hintId : undefined}
          className={className}
          {...registration}
          {...props}
        />
        {hasError ? (
          <p id={errorId} role="alert" className="text-sm font-medium text-destructive">
            {error}
          </p>
        ) : null}
        {showHint ? (
          <p id={hintId} className={cn("text-sm text-muted-foreground")}>
            {hint}
          </p>
        ) : null}
      </div>
    );
  },
);
TextField.displayName = "TextField";
