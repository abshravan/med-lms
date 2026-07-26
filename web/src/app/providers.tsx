"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

import { createQueryClient } from "@/lib/query/client";

/**
 * Client-side providers.
 *
 * The QueryClient is created in `useState` rather than at module scope. At module
 * scope it would be shared across every request during server rendering, leaking
 * one user's cached profile into another user's response — a real data-leak class
 * of bug, not a theoretical one.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(createQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
