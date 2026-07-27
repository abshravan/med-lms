import type { Metadata } from "next";

import { CourseEditor } from "@/features/courses/components/course-editor";

export const metadata: Metadata = { title: "Edit course" };

interface EditCoursePageProps {
  params: Promise<{ courseId: string }>;
}

export default async function EditCoursePage({ params }: EditCoursePageProps) {
  const { courseId } = await params;
  return <CourseEditor courseId={courseId} />;
}
