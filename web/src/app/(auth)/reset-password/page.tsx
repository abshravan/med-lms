import type { Metadata } from "next";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ResetPasswordForm } from "@/features/auth/components/reset-password-form";

export const metadata: Metadata = { title: "Choose a new password" };

interface ResetPasswordPageProps {
  searchParams: Promise<{ token?: string; error?: string }>;
}

export default async function ResetPasswordPage({
  searchParams,
}: ResetPasswordPageProps) {
  const params = await searchParams;

  // Better Auth appends `?error=INVALID_TOKEN` when it rejects the link before we
  // ever render. Normalising that to a null token reuses the invalid-link state
  // instead of showing a form that cannot succeed.
  const token =
    params.error !== undefined || params.token === undefined ? null : params.token;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Choose a new password</CardTitle>
        <CardDescription>
          Signing in elsewhere will be ended once your password changes.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResetPasswordForm token={token} />
      </CardContent>
    </Card>
  );
}
