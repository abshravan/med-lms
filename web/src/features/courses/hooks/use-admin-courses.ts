"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminCoursesApi } from "@/features/courses/api";
import type {
  CourseFormInput,
  LessonFormInput,
  ModuleFormInput,
} from "@/features/courses/schemas";
import type {
  ContentStatus,
  CourseDetail,
  CourseSummary,
  Page,
} from "@/features/courses/types";
import { ApiError } from "@/lib/api/errors";
import { courseKeys } from "@/features/courses/hooks/use-catalogue";

export const adminCourseKeys = {
  all: ["admin", "courses"] as const,
  list: (status: ContentStatus | "all") => [...adminCourseKeys.all, "list", status] as const,
  detail: (courseId: string) => [...adminCourseKeys.all, "detail", courseId] as const,
} as const;

/**
 * Invalidate everything a catalogue mutation could have changed.
 *
 * Centralised because the failure mode is silent: forget to invalidate the
 * student-facing key and an admin publishes a course that never appears in the
 * catalogue until the cache happens to expire.
 */
function invalidateCatalogue(client: QueryClient, courseId?: string): void {
  void client.invalidateQueries({ queryKey: adminCourseKeys.all });
  void client.invalidateQueries({ queryKey: courseKeys.all });
  if (courseId !== undefined) {
    void client.invalidateQueries({ queryKey: adminCourseKeys.detail(courseId) });
  }
}

export function useAdminCourses(
  status: ContentStatus | "all" = "all",
): UseQueryResult<Page<CourseSummary>, ApiError> {
  return useQuery<Page<CourseSummary>, ApiError>({
    queryKey: adminCourseKeys.list(status),
    queryFn: ({ signal }) =>
      adminCoursesApi.list(
        { limit: 50, ...(status !== "all" ? { status } : {}) },
        signal,
      ),
  });
}

export function useAdminCourse(courseId: string): UseQueryResult<CourseDetail, ApiError> {
  return useQuery<CourseDetail, ApiError>({
    queryKey: adminCourseKeys.detail(courseId),
    queryFn: ({ signal }) => adminCoursesApi.get(courseId, signal),
    enabled: courseId.length > 0,
  });
}

export function useCreateCourse(): UseMutationResult<
  CourseDetail,
  ApiError,
  CourseFormInput
> {
  const client = useQueryClient();
  return useMutation<CourseDetail, ApiError, CourseFormInput>({
    mutationFn: adminCoursesApi.create,
    onSuccess: () => invalidateCatalogue(client),
  });
}

export function useUpdateCourse(
  courseId: string,
): UseMutationResult<CourseDetail, ApiError, Partial<CourseFormInput>> {
  const client = useQueryClient();
  return useMutation<CourseDetail, ApiError, Partial<CourseFormInput>>({
    mutationFn: (input) => adminCoursesApi.update(courseId, input),
    onSuccess: (course) => {
      client.setQueryData(adminCourseKeys.detail(courseId), course);
      invalidateCatalogue(client);
    },
  });
}

/**
 * Publish or archive a course.
 *
 * One hook for both because they are the same shape and always invalidate the
 * same keys; splitting them would duplicate the invalidation logic.
 */
export function useCourseLifecycle(
  courseId: string,
): UseMutationResult<CourseDetail, ApiError, "publish" | "archive"> {
  const client = useQueryClient();
  return useMutation<CourseDetail, ApiError, "publish" | "archive">({
    mutationFn: (action) =>
      action === "publish"
        ? adminCoursesApi.publish(courseId)
        : adminCoursesApi.archive(courseId),
    onSuccess: (course) => {
      client.setQueryData(adminCourseKeys.detail(courseId), course);
      invalidateCatalogue(client);
    },
  });
}

// ── Modules ──────────────────────────────────────────────────────────────────

export function useCreateModule(
  courseId: string,
): UseMutationResult<unknown, ApiError, ModuleFormInput> {
  const client = useQueryClient();
  return useMutation<unknown, ApiError, ModuleFormInput>({
    mutationFn: (input) => adminCoursesApi.createModule(courseId, input),
    onSuccess: () => invalidateCatalogue(client, courseId),
  });
}

export function useDeleteModule(
  courseId: string,
): UseMutationResult<void, ApiError, string> {
  const client = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (moduleId) => adminCoursesApi.deleteModule(moduleId),
    onSuccess: () => invalidateCatalogue(client, courseId),
  });
}

export function useReorderModules(
  courseId: string,
): UseMutationResult<unknown, ApiError, string[]> {
  const client = useQueryClient();
  return useMutation<unknown, ApiError, string[]>({
    mutationFn: (orderedIds) => adminCoursesApi.reorderModules(courseId, orderedIds),
    onSuccess: () => invalidateCatalogue(client, courseId),
  });
}

// ── Lessons ──────────────────────────────────────────────────────────────────

export function useCreateLesson(
  courseId: string,
): UseMutationResult<unknown, ApiError, { moduleId: string; input: LessonFormInput }> {
  const client = useQueryClient();
  return useMutation<unknown, ApiError, { moduleId: string; input: LessonFormInput }>({
    mutationFn: ({ moduleId, input }) => adminCoursesApi.createLesson(moduleId, input),
    onSuccess: () => invalidateCatalogue(client, courseId),
  });
}

export function useDeleteLesson(
  courseId: string,
): UseMutationResult<void, ApiError, string> {
  const client = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (lessonId) => adminCoursesApi.deleteLesson(lessonId),
    onSuccess: () => invalidateCatalogue(client, courseId),
  });
}

export function useReorderLessons(
  courseId: string,
): UseMutationResult<unknown, ApiError, { moduleId: string; orderedIds: string[] }> {
  const client = useQueryClient();
  return useMutation<unknown, ApiError, { moduleId: string; orderedIds: string[] }>({
    mutationFn: ({ moduleId, orderedIds }) =>
      adminCoursesApi.reorderLessons(moduleId, orderedIds),
    onSuccess: () => invalidateCatalogue(client, courseId),
  });
}
