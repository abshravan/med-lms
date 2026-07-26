import { cn } from "@/lib/utils";

/**
 * Loading placeholder.
 *
 * `aria-hidden` because a skeleton is decorative — the surrounding region carries
 * `aria-busy`, which is what assistive technology should announce instead of a
 * series of meaningless boxes.
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}
