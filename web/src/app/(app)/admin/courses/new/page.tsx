import type { Metadata } from "next";
import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";
import { CourseForm } from "@/features/courses/components/course-form";

export const metadata: Metadata = { title: "New course" };

export default function NewCoursePage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="space-y-1">
        <Link
          href="/admin/courses"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to courses
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">New course</h1>
      </div>
      <Card>
        <CardContent className="pt-6">
          <CourseForm />
        </CardContent>
      </Card>
    </div>
  );
}
