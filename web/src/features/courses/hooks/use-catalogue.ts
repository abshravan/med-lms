"use client";

import {
  useInfiniteQuery,
  useQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { fetchCatalogue, fetchCourse, fetchLesson } from "@/features/courses/api";
import type {
  CatalogueQuery,
  CourseDetail,
  CourseSummary,
  LessonDetail,
  Page,
} from "@/features/courses/types";
import { ApiError } from "@/lib/api/errors";

/**
 * Query keys for the catalogue.
 *
 * Filters are part of the key so switching specialty is a separate cache entry
 * rather than a refetch that flashes the previous results.
 */
export const courseKeys = {
  all: ["courses"] as const,
  catalogue: (filters: CatalogueQuery) =>
    [...courseKeys.all, "catalogue", filters] as const,
  detail: (slug: string) => [...courseKeys.all, "detail", slug] as const,
  lesson: (courseSlug: string, lessonSlug: string) =>
    [...courseKeys.all, "lesson", courseSlug, lessonSlug] as const,
} as const;

const PAGE_SIZE = 12;

/**
 * The paginated catalogue.
 *
 * `useInfiniteQuery` rather than page-number state, because the API is
 * cursor-based: there is no page *number* to hold, only "what comes after this".
 * Modelling it as pages would mean inventing an index the server does not have.
 */
export function useCatalogue(
  filters: CatalogueQuery,
): UseInfiniteQueryResult<InfiniteData<Page<CourseSummary>, string | undefined>, ApiError> {
  return useInfiniteQuery<
    Page<CourseSummary>,
    ApiError,
    // The third parameter is the *selected* shape, which for an infinite query is
    // the accumulated `InfiniteData` — not a single page.
    InfiniteData<Page<CourseSummary>, string | undefined>,
    ReturnType<typeof courseKeys.catalogue>,
    string | undefined
  >({
    queryKey: courseKeys.catalogue(filters),
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      fetchCatalogue(
        {
          ...filters,
          limit: PAGE_SIZE,
          ...(pageParam !== undefined ? { cursor: pageParam } : {}),
        },
        signal,
      ),
    // Returning undefined is what tells TanStack Query there is nothing more.
    getNextPageParam: (lastPage) => lastPage.pagination.next_cursor ?? undefined,
    // The catalogue changes when an admin publishes, not minute to minute.
    staleTime: 60_000,
  });
}

export function useCourse(
  slug: string,
  options: { enabled?: boolean } = {},
): UseQueryResult<CourseDetail, ApiError> {
  return useQuery<CourseDetail, ApiError>({
    queryKey: courseKeys.detail(slug),
    queryFn: ({ signal }) => fetchCourse(slug, signal),
    enabled: (options.enabled ?? true) && slug.length > 0,
    staleTime: 60_000,
  });
}

export function useLesson(
  courseSlug: string,
  lessonSlug: string,
): UseQueryResult<LessonDetail, ApiError> {
  return useQuery<LessonDetail, ApiError>({
    queryKey: courseKeys.lesson(courseSlug, lessonSlug),
    queryFn: ({ signal }) => fetchLesson(courseSlug, lessonSlug, signal),
    enabled: courseSlug.length > 0 && lessonSlug.length > 0,
    staleTime: 60_000,
  });
}
