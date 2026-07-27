import * as React from "react";

import { cn } from "@/lib/utils";

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 0–100. Omit for an indeterminate bar. */
  value?: number | undefined;
  /** Accessible name, e.g. "Uploading". */
  label: string;
}

/**
 * A progress bar.
 *
 * Exposes the real ARIA progressbar role with `aria-valuenow`, so a screen
 * reader announces "45 percent" rather than nothing. When `value` is undefined
 * the bar is indeterminate and `aria-valuenow` is omitted — which is what tells
 * assistive technology the duration is unknown, instead of implying zero.
 */
export function Progress({ value, label, className, ...props }: ProgressProps) {
  const isDeterminate = value !== undefined && Number.isFinite(value);
  const clamped = isDeterminate ? Math.min(100, Math.max(0, value)) : undefined;

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      {...(clamped !== undefined ? { "aria-valuenow": clamped } : {})}
      className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)}
      {...props}
    >
      <div
        className={cn(
          "h-full rounded-full bg-primary transition-[width] duration-200",
          clamped === undefined && "w-1/3 animate-pulse",
        )}
        style={clamped !== undefined ? { width: `${clamped}%` } : undefined}
      />
    </div>
  );
}
