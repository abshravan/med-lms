import { BookOpen, Clock } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  DIFFICULTY_LABELS,
  formatDuration,
  type CourseSummary,
} from "@/features/courses/types";

export interface CourseCardProps {
  course: CourseSummary;
}

/**
 * A course in the catalogue grid.
 *
 * The whole card is a single link rather than a card containing a "View" button:
 * one large target is easier to hit on mobile, and it keeps the tab order to one
 * stop per course instead of several.
 */
export function CourseCard({ course }: CourseCardProps) {
  return (
    <Card className="group h-full transition-colors hover:border-primary/50">
      <Link
        href={`/courses/${course.slug}`}
        className="flex h-full flex-col rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <CardHeader className="space-y-2 pb-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="neutral">{DIFFICULTY_LABELS[course.difficulty]}</Badge>
            {course.specialty !== null ? (
              <Badge variant="outline">{course.specialty}</Badge>
            ) : null}
          </div>
          <h2 className="text-lg font-semibold leading-snug group-hover:text-primary">
            {course.title}
          </h2>
          {course.subtitle !== null ? (
            <p className="line-clamp-2 text-sm text-muted-foreground">
              {course.subtitle}
            </p>
          ) : null}
        </CardHeader>

        <CardContent className="mt-auto flex items-center gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <BookOpen className="h-4 w-4" aria-hidden="true" />
            {course.lesson_count} {course.lesson_count === 1 ? "lesson" : "lessons"}
          </span>
          {course.total_duration_seconds > 0 ? (
            <span className="flex items-center gap-1.5">
              <Clock className="h-4 w-4" aria-hidden="true" />
              {formatDuration(course.total_duration_seconds)}
            </span>
          ) : null}
        </CardContent>
      </Link>
    </Card>
  );
}
