"use client";

import Link from "next/link";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { useSignOut } from "@/features/auth/hooks/use-auth-actions";

export interface AppHeaderProps {
  displayName: string;
  email: string;
  emailVerified: boolean;
}

/**
 * Application header with the sign-out control.
 *
 * A client component because sign-out is interactive, but the identity it displays
 * is passed down from the server layout — so the header never has to fetch the
 * session itself, and there is no authenticated-but-empty flash on first paint.
 */
export function AppHeader({ displayName, email, emailVerified }: AppHeaderProps) {
  const { signOut, isSigningOut } = useSignOut();

  return (
    <header className="border-b border-border">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-4">
        <Link href="/dashboard" className="text-lg font-bold tracking-tight text-primary">
          MedLMS
        </Link>

        <div className="flex items-center gap-4">
          <div className="hidden text-right sm:block">
            <p className="text-sm font-medium leading-tight">{displayName}</p>
            <p className="text-xs text-muted-foreground">{email}</p>
          </div>

          {!emailVerified ? (
            <Button asChild variant="outline" size="sm">
              <Link href="/verify-email">Verify email</Link>
            </Button>
          ) : null}

          <Button
            onClick={() => void signOut()}
            loading={isSigningOut}
            variant="ghost"
            size="sm"
          >
            {isSigningOut ? "Signing out…" : "Sign out"}
          </Button>
        </div>
      </div>
    </header>
  );
}
