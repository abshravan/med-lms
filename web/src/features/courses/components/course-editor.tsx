"use client";

import Link from "next/link";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CourseForm } from "@/features/courses/components/course-form";
import { CourseOutlineEditor } from "@/features/courses/components/course-outline-editor";
import {
  useAdminCourse,
  useCourseLifecycle,
} from "@/features/courses/hooks/use-admin-courses";
import { STATUS_LABELS, type ContentStatus } from "@/features/courses/types";

const STATUS_VARIANT: Record<ContentStatus, "success" | "warning" | "neutral"> = {
  published: "success",
  draft: "warning",
  archived: "neutral",
};

export interface CourseEditorProps {
  courseId: string;
}

/**
 * The course authoring screen: details, outline, and lifecycle actions.
 *
 * Publishing is disabled — with the reason shown — when the course has no
 * lessons. The server enforces this too; surfacing it here means an author sees
 * *why* before clicking, rather than getting a validation error afterwards.
 */
export function CourseEditor({ courseId }: CourseEditorProps) {
  const { data: course, isPending, isError, error } = useAdminCourse(courseId);
  const lifecycle = useCourseLifecycle(courseId);
  const [actionError, setActionError] = React.useState<string | null>(null);

  if (isPending) {
    return (
      <div className="space-y-6" aria-busy="true">
        <Skeleton className="h-9 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-4">
        <Alert variant="destructive" title="We could not load this course">
          {error.userMessage}
        </Alert>
        <Button asChild variant="outline">
          <Link href="/admin/courses">Back to courses</Link>
        </Button>
      </div>
    );
  }

  const canPublish = course.lesson_count > 0 || course.modules.some((m) => m.lessons.length > 0);
  const isPublished = course.status === "published";

  const runAction = async (action: "publish" | "archive") => {
    setActionError(null);
    try {
      await lifecycle.mutateAsync(action);
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "That action could not be completed.",
      );
    }
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <Link
          href="/admin/courses"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to courses
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{course.title}</h1>
          <Badge variant={STATUS_VARIANT[course.status]}>
            {STATUS_LABELS[course.status]}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          <code>/courses/{course.slug}</code>
        </p>
      </div>

      {actionError !== null ? (
        <Alert variant="destructive">{actionError}</Alert>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-lg">Publication</CardTitle>
          <div className="flex gap-2">
            {!isPublished ? (
              <Button
                onClick={() => void runAction("publish")}
                loading={lifecycle.isPending}
                disabled={!canPublish}
              >
                Publish course
              </Button>
            ) : null}
            {course.status !== "archived" ? (
              <Button
                variant="outline"
                onClick={() => {
                  if (
                    window.confirm(
                      "Archive this course? It will be removed from the catalogue, but student history is kept.",
                    )
                  ) {
                    void runAction("archive");
                  }
                }}
                loading={lifecycle.isPending}
              >
                Archive
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {isPublished
              ? "This course is live in the catalogue. Publishing also made every draft lesson visible."
              : !canPublish
                ? "Add at least one lesson before publishing."
                : "Publishing makes this course and its draft lessons visible to students."}
          </p>
        </CardContent>
      </Card>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Course content</h2>
        <CourseOutlineEditor course={course} />
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Course details</h2>
        <Card>
          <CardContent className="pt-6">
            <CourseForm course={course} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
