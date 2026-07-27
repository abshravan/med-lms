"use client";

import { BookText, CircleHelp, Play } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  CONTENT_TYPE_LABELS,
  formatDuration,
  type CourseModule,
  type LessonContentType,
} from "@/features/courses/types";

const CONTENT_ICONS: Record<
  LessonContentType,
  React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>
> = {
  video: Play,
  reading: BookText,
  quiz: CircleHelp,
};

export interface CourseOutlineProps {
  courseSlug: string;
  modules: CourseModule[];
}

/**
 * A course's modules and lessons.
 *
 * Rendered as nested ordered lists rather than styled divs, because the ordering
 * *is* the meaning here — a screen reader should announce "lesson 3 of 8", and an
 * `<ol>` gives that for free.
 *
 * Modules with no visible lessons are shown rather than hidden: a student
 * scanning the outline should see that a section exists and is not yet released,
 * instead of finding a gap in the numbering.
 */
export function CourseOutline({ courseSlug, modules }: CourseOutlineProps) {
  if (modules.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          This course does not have any lessons yet.
        </CardContent>
      </Card>
    );
  }

  return (
    <ol className="space-y-4">
      {modules.map((module, moduleIndex) => (
        <li key={module.id}>
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-baseline gap-3">
                <span className="text-sm font-medium text-muted-foreground">
                  {String(moduleIndex + 1).padStart(2, "0")}
                </span>
                <div className="space-y-1">
                  <CardTitle className="text-base">{module.title}</CardTitle>
                  {module.summary !== null ? (
                    <p className="text-sm text-muted-foreground">{module.summary}</p>
                  ) : null}
                </div>
              </div>
            </CardHeader>

            <CardContent>
              {module.lessons.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Lessons for this module are coming soon.
                </p>
              ) : (
                <ol className="divide-y divide-border">
                  {module.lessons.map((lesson) => {
                    const Icon = CONTENT_ICONS[lesson.content_type];
                    return (
                      <li key={lesson.id}>
                        <Link
                          href={`/courses/${courseSlug}/lessons/${lesson.slug}`}
                          className="flex items-center gap-3 py-3 text-sm transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <Icon
                            className="h-4 w-4 shrink-0 text-muted-foreground"
                            aria-hidden={true}
                          />
                          <span className="flex-1 font-medium">{lesson.title}</span>
                          {lesson.is_free_preview ? (
                            <Badge variant="success">Free preview</Badge>
                          ) : null}
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {/* The type is announced as text so the icon can stay decorative. */}
                            <span className="sr-only">
                              {CONTENT_TYPE_LABELS[lesson.content_type]},{" "}
                            </span>
                            {formatDuration(lesson.duration_seconds)}
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ol>
              )}
            </CardContent>
          </Card>
        </li>
      ))}
    </ol>
  );
}
