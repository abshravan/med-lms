import { cva, type VariantProps } from "class-variance-authority";
import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative flex w-full gap-3 rounded-md border p-4 text-sm",
  {
    variants: {
      variant: {
        info: "border-border bg-muted text-foreground",
        success:
          "border-emerald-500/40 bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100",
        destructive:
          "border-destructive/40 bg-destructive/10 text-destructive dark:text-destructive-foreground",
      },
    },
    defaultVariants: { variant: "info" },
  },
);

const icons = {
  info: Info,
  success: CheckCircle2,
  destructive: AlertCircle,
} as const;

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  title?: string;
}

/**
 * Inline status message.
 *
 * `role` is derived from the variant: errors announce assertively so a screen
 * reader interrupts with a failed sign-in, while informational messages are
 * polite and wait their turn.
 */
const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "info", title, children, ...props }, ref) => {
    const resolved = variant ?? "info";
    const Icon = icons[resolved];

    return (
      <div
        ref={ref}
        role={resolved === "destructive" ? "alert" : "status"}
        aria-live={resolved === "destructive" ? "assertive" : "polite"}
        className={cn(alertVariants({ variant: resolved }), className)}
        {...props}
      >
        <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="space-y-1">
          {title !== undefined ? <p className="font-medium">{title}</p> : null}
          {children !== undefined ? <div className="leading-relaxed">{children}</div> : null}
        </div>
      </div>
    );
  },
);
Alert.displayName = "Alert";

export { Alert, alertVariants };
