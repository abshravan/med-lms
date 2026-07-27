import type { Metadata } from "next";

import { CourseCatalogue } from "@/features/courses/components/course-catalogue";

export const metadata: Metadata = { title: "Courses" };

export default function CoursesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Courses</h1>
        <p className="text-sm text-muted-foreground">
          Browse the published catalogue and pick up where you left off.
        </p>
      </div>
      <CourseCatalogue />
    </div>
  );
}
