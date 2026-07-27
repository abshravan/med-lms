import type { Metadata } from "next";

import { LessonView } from "@/features/courses/components/lesson-view";

export const metadata: Metadata = { title: "Lesson" };

interface LessonPageProps {
  params: Promise<{ slug: string; lessonSlug: string }>;
}

export default async function LessonPage({ params }: LessonPageProps) {
  const { slug, lessonSlug } = await params;
  return <LessonView courseSlug={slug} lessonSlug={lessonSlug} />;
}
