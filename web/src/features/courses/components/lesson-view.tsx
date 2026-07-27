"use client";

import { Clock, Construction } from "lucide-react";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useLesson } from "@/features/courses/hooks/use-catalogue";
import { CONTENT_TYPE_LABELS, formatDuration } from "@/features/courses/types";
import { LessonVideoPlayer } from "@/features/media/components/lesson-video-player";

export interface LessonViewProps {
  courseSlug: string;
  lessonSlug: string;
}

/**
 * A single lesson.
 *
 * The player and note body are deliberately absent: video delivery is Feature 3
 * and lesson notes are Feature 4. This renders the lesson's metadata and an
 * explicit placeholder rather than pretending the content exists — a blank area
 * would read as a bug.
 */
export function LessonView({ courseSlug, lessonSlug }: LessonViewProps) {
  const { data: lesson, isPending, isError, error } = useLesson(courseSlug, lessonSlug);

  if (isPending) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (isError) {
    const isMissing = error.code === "NOT_FOUND";
    return (
      <div className="space-y-4">
        <Alert
          variant={isMissing ? "info" : "destructive"}
          title={isMissing ? "Lesson not available" : "We could not load this lesson"}
        >
          {isMissing
            ? "This lesson may not be published yet, or the link may be out of date."
            : error.userMessage}
        </Alert>
        <Button asChild variant="outline">
          <Link href={`/courses/${courseSlug}`}>Back to course</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link
        href={`/courses/${courseSlug}`}
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        ← Back to course
      </Link>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="neutral">{CONTENT_TYPE_LABELS[lesson.content_type]}</Badge>
          {lesson.is_free_preview ? <Badge variant="success">Free preview</Badge> : null}
          {lesson.duration_seconds !== null ? (
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock className="h-4 w-4" aria-hidden="true" />
              {formatDuration(lesson.duration_seconds)}
            </span>
          ) : null}
        </div>

        <h1 className="text-2xl font-semibold tracking-tight">{lesson.title}</h1>
        {lesson.summary !== null ? (
          <p className="text-muted-foreground">{lesson.summary}</p>
        ) : null}
      </div>

      {lesson.content_type === "video" ? (
        <LessonVideoPlayer courseSlug={courseSlug} lessonSlug={lessonSlug} />
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Construction className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
            <div>
              <p className="font-medium">Lesson content is coming soon</p>
              <p className="text-sm text-muted-foreground">
                {lesson.content_type === "reading"
                  ? "Lesson notes arrive with the notes feature."
                  : "Quizzes arrive with the assessment feature."}
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
