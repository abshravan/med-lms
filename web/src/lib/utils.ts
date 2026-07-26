import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names, resolving Tailwind conflicts.
 *
 * `clsx` handles conditionals; `tailwind-merge` ensures a later class wins over an
 * earlier one in the same utility group (so `cn("p-2", "p-4")` yields `p-4`
 * rather than both). This is what makes component `className` overrides work
 * predictably.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
