import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 text-center">
      <div className="space-y-2">
        <p className="text-sm font-medium text-muted-foreground">404</p>
        <h1 className="text-3xl font-semibold tracking-tight">Page not found</h1>
        <p className="text-muted-foreground">
          The page you were looking for does not exist or has moved.
        </p>
      </div>
      <Button asChild>
        <Link href="/">Back to home</Link>
      </Button>
    </main>
  );
}
