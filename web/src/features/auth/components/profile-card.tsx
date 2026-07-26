"use client";

import { AlertCircle } from "lucide-react";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useProfile } from "@/features/auth/hooks/use-profile";

/**
 * The caller's profile, fetched from the FastAPI domain API.
 *
 * This component is the end-to-end proof that the auth bridge works: it mints an
 * access token from Better Auth, sends it to FastAPI, and renders the verified
 * result. If the token, JWKS fetch, signature check, or profile provisioning were
 * broken, this would show an error rather than data.
 *
 * All three states are handled explicitly — loading, error, and success — because
 * a component that only renders the happy path is a component that shows a blank
 * box in production.
 */
export function ProfileCard() {
  const { data: profile, isPending, isError, error, refetch, isRefetching } = useProfile();

  if (isPending) {
    return (
      <Card aria-busy="true">
        <CardHeader>
          <CardTitle>Your profile</CardTitle>
          <CardDescription>Loading your details…</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-3/5" />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Your profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Alert variant="destructive" title="We could not load your profile">
            {error.userMessage}
            {error.requestId !== null ? (
              <p className="mt-2 text-xs opacity-80">
                Reference: <code>{error.requestId}</code>
              </p>
            ) : null}
          </Alert>
          {/* Only offer a retry when retrying could actually help. */}
          {error.isRetryable ? (
            <Button onClick={() => void refetch()} loading={isRefetching} variant="outline">
              Try again
            </Button>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  const rows: { label: string; value: string }[] = [
    { label: "Name", value: profile.display_name ?? "Not set" },
    { label: "Email", value: profile.email },
    { label: "Role", value: profile.role === "admin" ? "Administrator" : "Student" },
    { label: "Institution", value: profile.institution ?? "Not set" },
    {
      label: "Year of study",
      value: profile.year_of_study !== null ? String(profile.year_of_study) : "Not set",
    },
    { label: "Specialisation", value: profile.specialization ?? "Not set" },
    { label: "Timezone", value: profile.timezone },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your profile</CardTitle>
        <CardDescription>
          Verified by the domain API using your access token.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!profile.email_verified ? (
          <Alert variant="destructive" title="Email not verified">
            Verify your email address to unlock course content.
          </Alert>
        ) : null}

        <dl className="divide-y divide-border">
          {rows.map((row) => (
            <div key={row.label} className="flex justify-between gap-4 py-2 text-sm">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="font-medium">{row.value}</dd>
            </div>
          ))}
        </dl>

        {!profile.onboarding_completed ? (
          <p className="flex items-start gap-2 text-sm text-muted-foreground">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            Complete your profile so we can tailor content to your year and
            specialisation.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
