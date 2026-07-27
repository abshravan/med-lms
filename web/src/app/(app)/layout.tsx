import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/common/app-header";
import { auth } from "@/lib/auth/server";

/**
 * Authenticated shell.
 *
 * **This is the real gate for rendering.** Unlike middleware (which can only see
 * that a cookie exists), this runs on the Node runtime and validates the session
 * against the database before any protected content is rendered.
 *
 * Defence in depth: even if this were bypassed, every domain request still carries
 * a signed access token that FastAPI verifies independently. Neither layer alone
 * is trusted.
 */
export default async function AppLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const session = await auth.api.getSession({ headers: await headers() });

  if (session === null) {
    redirect("/login");
  }

  // A banned account may still hold a valid cookie until it expires. Checking here
  // means the ban takes effect on the next navigation, not in up to seven days.
  if (session.user.banned === true) {
    redirect("/login?error=account_suspended");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader
        displayName={session.user.name ?? session.user.email}
        email={session.user.email}
        emailVerified={session.user.emailVerified}
        isAdmin={session.user.role === "admin"}
      />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
