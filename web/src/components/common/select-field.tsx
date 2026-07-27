"use client";

import * as React from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectFieldProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "id" | "children"> {
  label: string;
  name: string;
  options: readonly SelectOption[];
  error?: string | undefined;
  hint?: string | undefined;
  /** Rendered as a leading empty option — use for optional filters. */
  placeholder?: string | undefined;
  registration?: UseFormRegisterReturn | undefined;
}

/**
 * A labelled select with the same validation and ARIA contract as `TextField`.
 *
 * Kept symmetrical with `TextField` on purpose: a form built from these two
 * components has consistent error placement and announcement without each form
 * re-deciding how that works.
 */
export const SelectField = React.forwardRef<HTMLSelectElement, SelectFieldProps>(
  (
    { label, name, options, error, hint, placeholder, registration, ...props },
    ref,
  ) => {
    const errorId = `${name}-error`;
    const hintId = `${name}-hint`;
    const hasError = error !== undefined && error.length > 0;
    const showHint = !hasError && hint !== undefined && hint.length > 0;

    return (
      <div className="space-y-2">
        <Label htmlFor={name}>{label}</Label>
        <Select
          id={name}
          ref={ref}
          aria-invalid={hasError}
          aria-describedby={hasError ? errorId : showHint ? hintId : undefined}
          {...registration}
          {...props}
        >
          {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
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
SelectField.displayName = "SelectField";
