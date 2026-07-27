import * as React from "react";

import { cn } from "@/lib/utils";

export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

/**
 * Native select.
 *
 * A native element rather than a custom listbox: it is keyboard-accessible and
 * screen-reader-correct for free, and on mobile it opens the platform picker,
 * which is a better experience than any re-implementation. A custom component is
 * only worth it for multi-select or rich option rendering, neither of which the
 * catalogue filters need.
 */
const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-[invalid=true]:border-destructive",
        className,
      )}
      {...props}
    />
  ),
);
Select.displayName = "Select";

export { Select };
