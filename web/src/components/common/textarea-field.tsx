"use client";

import * as React from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { Label } from "@/components/ui/label";
import { Textarea, type TextareaProps } from "@/components/ui/textarea";

export interface TextareaFieldProps extends Omit<TextareaProps, "id"> {
  label: string;
  name: string;
  error?: string | undefined;
  hint?: string | undefined;
  registration?: UseFormRegisterReturn | undefined;
}

/** A labelled textarea, matching `TextField`'s validation and ARIA contract. */
export const TextareaField = React.forwardRef<HTMLTextAreaElement, TextareaFieldProps>(
  ({ label, name, error, hint, registration, ...props }, ref) => {
    const errorId = `${name}-error`;
    const hintId = `${name}-hint`;
    const hasError = error !== undefined && error.length > 0;
    const showHint = !hasError && hint !== undefined && hint.length > 0;

    return (
      <div className="space-y-2">
        <Label htmlFor={name}>{label}</Label>
        <Textarea
          id={name}
          ref={ref}
          aria-invalid={hasError}
          aria-describedby={hasError ? errorId : showHint ? hintId : undefined}
          {...registration}
          {...props}
        />
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
  },
);
TextareaField.displayName = "TextareaField";
