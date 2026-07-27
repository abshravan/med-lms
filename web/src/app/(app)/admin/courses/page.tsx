import type { Metadata } from "next";

import { AdminCourseList } from "@/features/courses/components/admin-course-list";

export const metadata: Metadata = { title: "Manage courses" };

export default function AdminCoursesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Courses</h1>
        <p className="text-sm text-muted-foreground">
          Create, edit, and publish course content.
        </p>
      </div>
      <AdminCourseList />
    </div>
  );
}
