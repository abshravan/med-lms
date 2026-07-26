import type { Metadata } from "next";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { LoginForm } from "@/features/auth/components/login-form";

export const metadata: Metadata = { title: "Sign in" };

/** `searchParams` is a Promise in Next 15 and must be awaited. */
interface LoginPageProps {
  searchParams: Promise<{ next?: string }>;
}

/**
 * Validate the post-login destination.
 *
 * Duplicated from middleware deliberately: this value reaches the client and gets
 * handed to `router.replace`, so it must be re-validated at the point of use.
 * Trusting that middleware already checked it is exactly how open redirects
 * survive a refactor.
 */
function safeNext(value: string | undefined): string {
  if (value === undefined || !value.startsWith("/") || value.startsWith("//")) {
    return "/dashboard";
  }
  return value;
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Welcome back</CardTitle>
        <CardDescription>Sign in to continue where you left off.</CardDescription>
      </CardHeader>
      <CardContent>
        <LoginForm redirectTo={safeNext(params.next)} />
      </CardContent>
    </Card>
  );
}
