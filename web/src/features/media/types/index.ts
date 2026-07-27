/**
 * Media types.
 *
 * Mirrors `backend/app/schemas/media.py`.
 */

export type MediaKind = "lesson_video" | "course_cover" | "lesson_attachment";
export type MediaStatus = "pending" | "ready" | "failed";

export interface UploadTicket {
  asset_id: string;
  upload_url: string;
  method: string;
  /** Must be sent verbatim — they are part of the upload signature. */
  headers: Record<string, string>;
  expires_in_seconds: number;
  storage_key: string;
}

export interface MediaAsset {
  id: string;
  kind: MediaKind;
  status: MediaStatus;
  original_filename: string;
  content_type: string;
  size_bytes: number | null;
  confirmed_at: string | null;
  created_at: string;
}

export interface PlaybackTicket {
  url: string;
  expires_in_seconds: number;
  content_type: string;
  duration_seconds: number | null;
}

/** Mirrors `ALLOWED_CONTENT_TYPES` on the server. */
export const ACCEPTED_TYPES: Record<MediaKind, readonly string[]> = {
  lesson_video: ["video/mp4", "video/webm", "video/quicktime"],
  course_cover: ["image/jpeg", "image/png", "image/webp"],
  lesson_attachment: ["application/pdf"],
};

/** Mirrors the per-kind ceilings in `Settings`. */
export const MAX_BYTES: Record<MediaKind, number> = {
  lesson_video: 2 * 1024 ** 3,
  course_cover: 10 * 1024 ** 2,
  lesson_attachment: 50 * 1024 ** 2,
};

/** Build an `accept` attribute for a file input. */
export function acceptAttribute(kind: MediaKind): string {
  return ACCEPTED_TYPES[kind].join(",");
}

/** Human-readable byte size. */
export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes <= 0) {
    return "—";
  }
  const units = ["B", "KB", "MB", "GB"] as const;
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  // Whole numbers for bytes and kilobytes; one decimal above that.
  const rounded = unitIndex <= 1 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unitIndex]}`;
}

/**
 * Client-side pre-flight check.
 *
 * A courtesy, not a control — the server validates independently and verifies
 * the real size after upload. This exists so a student-sized mistake (wrong file,
 * 4 GB export) fails in a second rather than after a long upload.
 */
export function validateFile(
  file: File,
  kind: MediaKind,
): { ok: true } | { ok: false; message: string } {
  if (!ACCEPTED_TYPES[kind].includes(file.type)) {
    return {
      ok: false,
      message: `That file type is not accepted. Allowed: ${ACCEPTED_TYPES[kind].join(", ")}.`,
    };
  }
  if (file.size > MAX_BYTES[kind]) {
    return {
      ok: false,
      message: `That file is too large. Maximum ${formatBytes(MAX_BYTES[kind])}.`,
    };
  }
  if (file.size === 0) {
    return { ok: false, message: "That file is empty." };
  }
  return { ok: true };
}
