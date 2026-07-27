import type { Metadata } from "next";

import { CourseDetailView } from "@/features/courses/components/course-detail-view";

export const metadata: Metadata = { title: "Course" };

interface CoursePageProps {
  params: Promise<{ slug: string }>;
}

export default async function CoursePage({ params }: CoursePageProps) {
  const { slug } = await params;
  return <CourseDetailView slug={slug} />;
}
