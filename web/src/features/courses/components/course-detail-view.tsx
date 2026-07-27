"use client";

import { BookOpen, Clock } from "lucide-react";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CourseOutline } from "@/features/courses/components/course-outline";
import { useCourse } from "@/features/courses/hooks/use-catalogue";
import { DIFFICULTY_LABELS, formatDuration } from "@/features/courses/types";

export interface CourseDetailViewProps {
  slug: string;
}

/**
 * A course landing page.
 *
 * Fetched client-side so the outline stays in the same TanStack Query cache the
 * catalogue populates — navigating from a course card renders instantly from
 * cache and revalidates in the background, rather than blocking on a server
 * round-trip for data the client already has.
 */
export function CourseDetailView({ slug }: CourseDetailViewProps) {
  const { data: course, isPending, isError, error, refetch, isRefetching } = useCourse(slug);

  if (isPending) {
    return (
      <div className="space-y-6" aria-busy="true">
        <div className="space-y-3">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-9 w-2/3" />
          <Skeleton className="h-5 w-full max-w-xl" />
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (isError) {
    // A missing course is an expected outcome (stale bookmark, unpublished
    // content), so it gets a helpful page rather than an error banner.
    const isMissing = error.code === "NOT_FOUND";

    return (
      <div className="space-y-4">
        <Alert
          variant={isMissing ? "info" : "destructive"}
          title={isMissing ? "Course not available" : "We could not load this course"}
        >
          {isMissing
            ? "This course may have been unpublished, or the link may be out of date."
            : error.userMessage}
        </Alert>
        <div className="flex gap-3">
          <Button asChild variant="outline">
            <Link href="/courses">Back to catalogue</Link>
          </Button>
          {!isMissing && error.isRetryable ? (
            <Button onClick={() => void refetch()} loading={isRefetching}>
              Try again
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <Link
          href="/courses"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to catalogue
        </Link>

        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="neutral">{DIFFICULTY_LABELS[course.difficulty]}</Badge>
          {course.specialty !== null ? (
            <Badge variant="outline">{course.specialty}</Badge>
          ) : null}
        </div>

        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">{course.title}</h1>
          {course.subtitle !== null ? (
            <p className="text-lg text-muted-foreground">{course.subtitle}</p>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <BookOpen className="h-4 w-4" aria-hidden="true" />
            {course.lesson_count} {course.lesson_count === 1 ? "lesson" : "lessons"}
          </span>
          {course.total_duration_seconds > 0 ? (
            <span className="flex items-center gap-1.5">
              <Clock className="h-4 w-4" aria-hidden="true" />
              {formatDuration(course.total_duration_seconds)} total
            </span>
          ) : null}
        </div>
      </div>

      {course.description !== null ? (
        <Card>
          <CardHeader className="pb-2">
            <h2 className="text-lg font-semibold">About this course</h2>
          </CardHeader>
          <CardContent>
            {/* Rendered as plain text, deliberately: `description` is author-supplied
                and rendering it as HTML would be a stored-XSS vector. Markdown
                rendering with a sanitiser arrives with the notes feature. */}
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
              {course.description}
            </p>
          </CardContent>
        </Card>
      ) : null}

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Course content</h2>
        <CourseOutline courseSlug={course.slug} modules={course.modules} />
      </section>
    </div>
  );
}
