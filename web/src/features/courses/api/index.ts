/**
 * Domain-API calls for the course catalogue.
 *
 * Student and admin calls are kept in separate exported groups so it is obvious
 * at the import site which surface a component is touching.
 */

import { api } from "@/lib/api/client";
import type {
  CatalogueQuery,
  ContentStatus,
  CourseDetail,
  CourseModule,
  CourseSummary,
  LessonDetail,
  Page,
  ReorderResult,
} from "@/features/courses/types";
import type {
  CourseFormInput,
  LessonFormInput,
  ModuleFormInput,
} from "@/features/courses/schemas";

/** Build a query string, omitting empty values so the URL stays clean. */
function toQueryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded.length > 0 ? `?${encoded}` : "";
}

// ── Student ──────────────────────────────────────────────────────────────────

export function fetchCatalogue(
  query: CatalogueQuery,
  signal?: AbortSignal,
): Promise<Page<CourseSummary>> {
  const path = `/api/v1/courses${toQueryString({
    q: query.q,
    specialty: query.specialty,
    difficulty: query.difficulty,
    limit: query.limit,
    cursor: query.cursor,
  })}`;
  return api.get<Page<CourseSummary>>(path, signal !== undefined ? { signal } : {});
}

export function fetchCourse(slug: string, signal?: AbortSignal): Promise<CourseDetail> {
  return api.get<CourseDetail>(
    `/api/v1/courses/${encodeURIComponent(slug)}`,
    signal !== undefined ? { signal } : {},
  );
}

export function fetchLesson(
  courseSlug: string,
  lessonSlug: string,
  signal?: AbortSignal,
): Promise<LessonDetail> {
  return api.get<LessonDetail>(
    `/api/v1/courses/${encodeURIComponent(courseSlug)}/lessons/${encodeURIComponent(lessonSlug)}`,
    signal !== undefined ? { signal } : {},
  );
}

// ── Admin ────────────────────────────────────────────────────────────────────

export const adminCoursesApi = {
  list(
    params: { status?: ContentStatus; limit?: number; cursor?: string },
    signal?: AbortSignal,
  ): Promise<Page<CourseSummary>> {
    const path = `/api/v1/admin/courses${toQueryString({
      status: params.status,
      limit: params.limit,
      cursor: params.cursor,
    })}`;
    return api.get<Page<CourseSummary>>(path, signal !== undefined ? { signal } : {});
  },

  get(courseId: string, signal?: AbortSignal): Promise<CourseDetail> {
    return api.get<CourseDetail>(
      `/api/v1/admin/courses/${courseId}`,
      signal !== undefined ? { signal } : {},
    );
  },

  create(input: CourseFormInput): Promise<CourseDetail> {
    return api.post<CourseDetail>("/api/v1/admin/courses", input);
  },

  update(courseId: string, input: Partial<CourseFormInput>): Promise<CourseDetail> {
    return api.patch<CourseDetail>(`/api/v1/admin/courses/${courseId}`, input);
  },

  publish(courseId: string): Promise<CourseDetail> {
    return api.post<CourseDetail>(`/api/v1/admin/courses/${courseId}/publish`);
  },

  archive(courseId: string): Promise<CourseDetail> {
    return api.post<CourseDetail>(`/api/v1/admin/courses/${courseId}/archive`);
  },

  createModule(courseId: string, input: ModuleFormInput): Promise<CourseModule> {
    return api.post<CourseModule>(`/api/v1/admin/courses/${courseId}/modules`, input);
  },

  updateModule(moduleId: string, input: Partial<ModuleFormInput>): Promise<CourseModule> {
    return api.patch<CourseModule>(`/api/v1/admin/modules/${moduleId}`, input);
  },

  deleteModule(moduleId: string): Promise<void> {
    return api.delete<void>(`/api/v1/admin/modules/${moduleId}`);
  },

  reorderModules(courseId: string, orderedIds: string[]): Promise<ReorderResult> {
    return api.put<ReorderResult>(`/api/v1/admin/courses/${courseId}/module-order`, {
      ordered_ids: orderedIds,
    });
  },

  createLesson(moduleId: string, input: LessonFormInput): Promise<LessonDetail> {
    return api.post<LessonDetail>(`/api/v1/admin/modules/${moduleId}/lessons`, input);
  },

  updateLesson(lessonId: string, input: Partial<LessonFormInput>): Promise<LessonDetail> {
    return api.patch<LessonDetail>(`/api/v1/admin/lessons/${lessonId}`, input);
  },

  deleteLesson(lessonId: string): Promise<void> {
    return api.delete<void>(`/api/v1/admin/lessons/${lessonId}`);
  },

  setLessonPublished(lessonId: string, published: boolean): Promise<LessonDetail> {
    const action = published ? "publish" : "unpublish";
    return api.post<LessonDetail>(`/api/v1/admin/lessons/${lessonId}/${action}`);
  },

  reorderLessons(moduleId: string, orderedIds: string[]): Promise<ReorderResult> {
    return api.put<ReorderResult>(`/api/v1/admin/modules/${moduleId}/lesson-order`, {
      ordered_ids: orderedIds,
    });
  },
} as const;
