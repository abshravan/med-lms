/**
 * Media API calls.
 *
 * Note the split: ticket request and confirmation go through the domain API
 * client (authenticated, enveloped), while the upload itself goes **directly to
 * storage** with a raw XHR and no `Authorization` header — the presigned URL is
 * the credential. Routing the bytes through `apiRequest` would defeat the point
 * of direct upload entirely.
 */

import { api } from "@/lib/api/client";
import type {
  MediaAsset,
  MediaKind,
  PlaybackTicket,
  UploadTicket,
} from "@/features/media/types";

export function requestUploadTicket(input: {
  kind: MediaKind;
  filename: string;
  content_type: string;
  size_bytes: number;
}): Promise<UploadTicket> {
  return api.post<UploadTicket>("/api/v1/admin/media/uploads", input);
}

export function confirmUpload(assetId: string): Promise<MediaAsset> {
  return api.post<MediaAsset>(`/api/v1/admin/media/uploads/${assetId}/confirm`, {});
}

export function deleteAsset(assetId: string): Promise<void> {
  return api.delete<void>(`/api/v1/admin/media/assets/${assetId}`);
}

export function attachLessonVideo(
  lessonId: string,
  assetId: string,
): Promise<unknown> {
  return api.put<unknown>(`/api/v1/admin/lessons/${lessonId}/video`, {
    asset_id: assetId,
  });
}

export function detachLessonVideo(lessonId: string): Promise<unknown> {
  return api.delete<unknown>(`/api/v1/admin/lessons/${lessonId}/video`);
}

export function fetchPlaybackTicket(
  courseSlug: string,
  lessonSlug: string,
  signal?: AbortSignal,
): Promise<PlaybackTicket> {
  return api.get<PlaybackTicket>(
    `/api/v1/courses/${encodeURIComponent(courseSlug)}/lessons/${encodeURIComponent(lessonSlug)}/playback`,
    signal !== undefined ? { signal } : {},
  );
}

export interface DirectUploadOptions {
  ticket: UploadTicket;
  file: File;
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

/**
 * Upload a file straight to object storage.
 *
 * **XHR rather than `fetch`.** `fetch` still exposes no upload progress — the
 * Streams-based upload API is not available across the browsers this product
 * targets. For a 500 MB lecture recording, a progress bar is not a nicety: with
 * no feedback, authors assume the page has hung and reload it mid-upload.
 *
 * The headers from the ticket are sent verbatim because they are part of the
 * signature; altering `Content-Type` invalidates the URL.
 */
export function uploadDirect(options: DirectUploadOptions): Promise<void> {
  const { ticket, file, onProgress, signal } = options;

  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(ticket.method, ticket.upload_url, true);

    for (const [header, value] of Object.entries(ticket.headers)) {
      request.setRequestHeader(header, value);
    }

    if (onProgress !== undefined) {
      request.upload.onprogress = (event: ProgressEvent) => {
        // `lengthComputable` is false for chunked encoding; reporting a bogus
        // fraction would make the bar jump backwards.
        if (event.lengthComputable && event.total > 0) {
          onProgress(event.loaded / event.total);
        }
      };
    }

    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve();
        return;
      }
      reject(
        new Error(
          `Upload failed (${request.status}). The link may have expired — try again.`,
        ),
      );
    };

    request.onerror = () =>
      reject(new Error("The upload could not be sent. Check your connection."));
    request.ontimeout = () => reject(new Error("The upload timed out."));
    request.onabort = () => reject(new DOMException("Upload aborted", "AbortError"));

    if (signal !== undefined) {
      if (signal.aborted) {
        request.abort();
        return;
      }
      signal.addEventListener("abort", () => request.abort(), { once: true });
    }

    request.send(file);
  });
}
