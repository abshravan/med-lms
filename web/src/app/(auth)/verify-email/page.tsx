import type { Metadata } from "next";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { VerifyEmailNotice } from "@/features/auth/components/verify-email-notice";
import { auth } from "@/lib/auth/server";
import { headers } from "next/headers";

export const metadata: Metadata = { title: "Verify your email" };

interface VerifyEmailPageProps {
  searchParams: Promise<{ sent?: string; error?: string }>;
}

/**
 * Post-registration verification notice.
 *
 * The email address is read from the server-side session rather than a query
 * parameter. A `?email=` parameter would be attacker-controllable and would let
 * this page be used to render an arbitrary address inside a legitimate-looking
 * MedLMS page — a neat phishing primitive. Reading the session avoids that
 * entirely.
 */
export default async function VerifyEmailPage({ searchParams }: VerifyEmailPageProps) {
  const params = await searchParams;
  const session = await auth.api.getSession({ headers: await headers() });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Verify your email</CardTitle>
        <CardDescription>
          One more step before you can access your courses.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <VerifyEmailNotice
          email={session?.user.email ?? null}
          justSent={params.sent === "1"}
          failed={params.error !== undefined}
        />
      </CardContent>
    </Card>
  );
}
