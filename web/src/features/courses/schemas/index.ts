/**
 * Course authoring validation.
 *
 * Mirrors `backend/app/schemas/course.py`, including its omissions: neither
 * schema here carries `status`, because publishing is an explicit action with
 * its own checks rather than a field an author can set. The server rejects it
 * with `extra="forbid"` regardless.
 */

import { z } from "zod";

export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const MAX_SLUG_LENGTH = 160;

const difficultyEnum = z.enum(["foundation", "intermediate", "advanced"]);
const contentTypeEnum = z.enum(["video", "reading", "quiz"]);

/**
 * Optional slug.
 *
 * A blank field means "derive it from the title", so an empty string is
 * normalised to `undefined` rather than sent as `""` — which the server would
 * reject. The pattern is enforced rather than auto-corrected, matching the
 * backend: a silently rewritten slug makes the resulting URL a surprise.
 */
const optionalSlug = z
  .string()
  .trim()
  .max(MAX_SLUG_LENGTH, "That slug is too long")
  .refine((value) => value === "" || SLUG_PATTERN.test(value), {
    message: "Use lowercase letters, numbers and single hyphens only",
  })
  .transform((value) => (value === "" ? undefined : value))
  .optional();

/** Trim, and treat an empty optional text field as absent. */
function optionalText(max: number, message: string) {
  return z
    .string()
    .trim()
    .max(max, message)
    .transform((value) => (value === "" ? undefined : value))
    .optional();
}

export const courseFormSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Title is required")
    .max(200, "That title is too long"),
  slug: optionalSlug,
  subtitle: optionalText(300, "That subtitle is too long"),
  description: optionalText(20_000, "That description is too long"),
  specialty: optionalText(120, "That specialty name is too long"),
  difficulty: difficultyEnum.default("foundation"),
});

export const moduleFormSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Title is required")
    .max(200, "That title is too long"),
  summary: optionalText(2000, "That summary is too long"),
});

export const lessonFormSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Title is required")
    .max(200, "That title is too long"),
  slug: optionalSlug,
  summary: optionalText(2000, "That summary is too long"),
  content_type: contentTypeEnum.default("video"),
  /**
   * Duration is entered in minutes but sent in seconds — see `minutesToSeconds`.
   * Capped at 24 hours, matching the server's constraint.
   */
  duration_seconds: z
    .number()
    .int("Enter a whole number")
    .positive("Duration must be greater than zero")
    .max(86_400, "That duration is unrealistically long")
    .optional(),
  is_free_preview: z.boolean().default(false),
});

export const catalogueFilterSchema = z.object({
  q: optionalText(120, "Search term is too long"),
  specialty: optionalText(120, "That specialty name is too long"),
  difficulty: difficultyEnum.optional(),
});

export type CourseFormInput = z.infer<typeof courseFormSchema>;
export type ModuleFormInput = z.infer<typeof moduleFormSchema>;
export type LessonFormInput = z.infer<typeof lessonFormSchema>;
export type CatalogueFilterInput = z.infer<typeof catalogueFilterSchema>;

/**
 * Convert a minutes input into the seconds the API expects.
 *
 * Authors think in minutes; the API stores seconds because the video pipeline
 * will report exact durations. The conversion lives here so both the create and
 * edit forms use the same rule.
 */
export function minutesToSeconds(minutes: number | undefined): number | undefined {
  if (minutes === undefined || Number.isNaN(minutes) || minutes <= 0) {
    return undefined;
  }
  return Math.round(minutes * 60);
}

/** Inverse of `minutesToSeconds`, for populating an edit form. */
export function secondsToMinutes(seconds: number | null): number | undefined {
  if (seconds === null || seconds <= 0) {
    return undefined;
  }
  return Math.round(seconds / 60);
}
