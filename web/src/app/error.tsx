"use client";

import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/**
 * Route-level error boundary.
 *
 * `error.message` is deliberately not rendered: in production it may contain
 * internal detail, and to a student it is noise either way. The `digest` is shown
 * instead, because it is the identifier support needs to find the server log.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error("[ui] unhandled render error", error.digest ?? error.name);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <div className="w-full max-w-md space-y-4">
        <Alert variant="destructive" title="Something went wrong">
          We hit an unexpected problem loading this page.
          {error.digest !== undefined ? (
            <p className="mt-2 text-xs opacity-80">
              Reference: <code>{error.digest}</code>
            </p>
          ) : null}
        </Alert>
        <Button onClick={reset} className="w-full">
          Try again
        </Button>
      </div>
    </main>
  );
}
