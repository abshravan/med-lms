import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "@/lib/auth/server";

/**
 * Admin shell.
 *
 * The role is read from the validated server session, so a student who guesses
 * an `/admin` URL is redirected before any admin UI renders. This is a rendering
 * guard, not the authorisation boundary — every admin API call is independently
 * checked by FastAPI's `require_role`, which re-reads the role from Postgres.
 * Removing this layout would leak the admin *interface*, never admin *data*.
 */
export default async function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const session = await auth.api.getSession({ headers: await headers() });

  if (session === null) {
    redirect("/login");
  }
  if (session.user.role !== "admin") {
    redirect("/dashboard");
  }

  return (
    <div className="space-y-6">
      <div className="rounded-md border border-dashed border-border px-4 py-2 text-sm text-muted-foreground">
        Admin area — changes here affect what every student sees.
      </div>
      {children}
    </div>
  );
}
