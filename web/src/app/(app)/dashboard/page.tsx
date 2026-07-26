import type { Metadata } from "next";

import { ProfileCard } from "@/features/auth/components/profile-card";

export const metadata: Metadata = { title: "Dashboard" };

/**
 * Dashboard placeholder.
 *
 * Intentionally minimal: authentication is the only feature built so far, and this
 * page exists to prove the whole chain works end-to-end (session → access token →
 * FastAPI verification → profile). Course content lands here in the next feature.
 */
export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Authentication is live. Course content arrives with the next feature.
        </p>
      </div>
      <ProfileCard />
    </div>
  );
}
