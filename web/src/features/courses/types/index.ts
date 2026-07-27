/**
 * Course catalogue types.
 *
 * Mirrors `backend/app/schemas/course.py`. Snake_case is preserved to match the
 * wire format, for the reason given in `features/auth/types`.
 */

export type ContentStatus = "draft" | "published" | "archived";
export type Difficulty = "foundation" | "intermediate" | "advanced";
export type LessonContentType = "video" | "reading" | "quiz";

export interface LessonSummary {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  content_type: LessonContentType;
  duration_seconds: number | null;
  is_free_preview: boolean;
  position: number;
}

export interface LessonDetail extends LessonSummary {
  course_id: string;
  module_id: string;
  status: ContentStatus;
  published_at: string | null;
}

export interface CourseModule {
  id: string;
  title: string;
  summary: string | null;
  position: number;
  lessons: LessonSummary[];
}

export interface CourseSummary {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  specialty: string | null;
  difficulty: Difficulty;
  status: ContentStatus;
  /** Short-lived signed URL, or null. The raw storage key is never exposed. */
  cover_image_url: string | null;
  lesson_count: number;
  total_duration_seconds: number;
  published_at: string | null;
}

export interface CourseDetail extends CourseSummary {
  description: string | null;
  modules: CourseModule[];
  created_at: string;
  updated_at: string;
}

/** Cursor pagination metadata, from `schemas/common.py::PaginationMeta`. */
export interface PaginationMeta {
  next_cursor: string | null;
  has_more: boolean;
  limit: number;
}

export interface Page<TItem> {
  items: TItem[];
  pagination: PaginationMeta;
}

export interface CatalogueQuery {
  q?: string;
  specialty?: string;
  difficulty?: Difficulty;
  limit?: number;
  cursor?: string;
}

export interface ReorderResultItem {
  id: string;
  position: number;
}

export interface ReorderResult {
  items: ReorderResultItem[];
}

/** Human-readable labels, kept beside the types so they cannot drift apart. */
export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  foundation: "Foundation",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

export const CONTENT_TYPE_LABELS: Record<LessonContentType, string> = {
  video: "Video",
  reading: "Reading",
  quiz: "Quiz",
};

export const STATUS_LABELS: Record<ContentStatus, string> = {
  draft: "Draft",
  published: "Published",
  archived: "Archived",
};

/**
 * Format a duration for display.
 *
 * Returns a compact form ("1h 5m", "45m", "30s") rather than a clock time,
 * because course lengths are scanned, not read precisely.
 */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds <= 0) {
    return "—";
  }
  // Sub-minute durations are reported in seconds. Checked first because
  // rounding to minutes would turn 45s into "1m" and make this branch
  // unreachable for anything above 30 seconds.
  if (seconds < 60) {
    return `${seconds}s`;
  }

  // Rounding to whole minutes before splitting means 3599s reads as "1h"
  // rather than "60m".
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  return `${minutes}m`;
}
