import Link from "next/link";

import { Button } from "@/components/ui/button";

/**
 * Landing page.
 *
 * Deliberately thin — marketing content is not part of the authentication feature.
 * Its job is to route visitors to sign-in or registration.
 */
export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 px-4 text-center">
      <div className="space-y-4">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">MedLMS</h1>
        <p className="mx-auto max-w-xl text-muted-foreground">
          Video lessons, lecture notes, AI-generated flashcards, quizzes, and
          AI-powered voice viva practice — in one place.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button asChild size="lg">
          <Link href="/register">Get started</Link>
        </Button>
        <Button asChild size="lg" variant="outline">
          <Link href="/login">Sign in</Link>
        </Button>
      </div>
    </main>
  );
}
