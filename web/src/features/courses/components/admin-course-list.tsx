"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAdminCourses } from "@/features/courses/hooks/use-admin-courses";
import {
  DIFFICULTY_LABELS,
  STATUS_LABELS,
  formatDuration,
  type ContentStatus,
} from "@/features/courses/types";

const STATUS_VARIANT: Record<ContentStatus, "success" | "warning" | "neutral"> = {
  published: "success",
  draft: "warning",
  archived: "neutral",
};

/** Every course an admin owns, in any state. */
export function AdminCourseList() {
  const [status, setStatus] = React.useState<ContentStatus | "all">("all");
  const { data, isPending, isError, error, refetch, isRefetching } =
    useAdminCourses(status);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="w-48 space-y-2">
          <Label htmlFor="admin-status-filter">Status</Label>
          <Select
            id="admin-status-filter"
            value={status}
            onChange={(event) => setStatus(event.target.value as ContentStatus | "all")}
          >
            <option value="all">All courses</option>
            <option value="draft">Drafts</option>
            <option value="published">Published</option>
            <option value="archived">Archived</option>
          </Select>
        </div>

        <Button asChild>
          <Link href="/admin/courses/new">
            <Plus className="h-4 w-4" aria-hidden="true" />
            New course
          </Link>
        </Button>
      </div>

      {isPending ? (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-20 w-full" />
          ))}
        </div>
      ) : null}

      {isError ? (
        <div className="space-y-4">
          <Alert variant="destructive" title="We could not load your courses">
            {error.userMessage}
          </Alert>
          {error.isRetryable ? (
            <Button onClick={() => void refetch()} loading={isRefetching} variant="outline">
              Try again
            </Button>
          ) : null}
        </div>
      ) : null}

      {!isPending && !isError && data.items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="font-medium">
              {status === "all" ? "No courses yet" : `No ${STATUS_LABELS[status].toLowerCase()} courses`}
            </p>
            <p className="text-sm text-muted-foreground">
              Create your first course to start building the catalogue.
            </p>
            <Button asChild>
              <Link href="/admin/courses/new">New course</Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {!isPending && !isError && data.items.length > 0 ? (
        <ul className="space-y-3">
          {data.items.map((course) => (
            <li key={course.id}>
              <Card className="transition-colors hover:border-primary/50">
                <Link
                  href={`/admin/courses/${course.id}`}
                  className="block rounded-lg p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="font-semibold">{course.title}</h2>
                        <Badge variant={STATUS_VARIANT[course.status]}>
                          {STATUS_LABELS[course.status]}
                        </Badge>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {course.specialty ?? "No specialty"} ·{" "}
                        {DIFFICULTY_LABELS[course.difficulty]}
                      </p>
                    </div>

                    <div className="text-right text-sm text-muted-foreground">
                      <p>
                        {course.lesson_count}{" "}
                        {course.lesson_count === 1 ? "lesson" : "lessons"}
                      </p>
                      <p>{formatDuration(course.total_duration_seconds)}</p>
                    </div>
                  </div>
                </Link>
              </Card>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
