"use client";

import { useQuery } from "@tanstack/react-query";
import { VideoOff } from "lucide-react";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchPlaybackTicket } from "@/features/media/api";
import type { PlaybackTicket } from "@/features/media/types";
import { ApiError } from "@/lib/api/errors";

export interface LessonVideoPlayerProps {
  courseSlug: string;
  lessonSlug: string;
}

/**
 * Plays a lesson's video from a short-lived signed URL.
 *
 * **Why the ticket is fetched rather than embedded in the lesson response.** A
 * signed URL is a bearer credential with a few minutes of life. Putting one in
 * the course outline would mean minting a URL for every lesson a student merely
 * scrolls past, and caching outline responses would cache expired links. One
 * ticket, fetched when the lesson is actually opened, is both cheaper and
 * shorter-lived.
 *
 * The ticket is refetched a little before it expires so a student who pauses
 * mid-lesson and resumes does not hit a 403 on the next range request.
 *
 * `controlsList="nodownload"` is a hint, not a control — anyone can read the
 * signed URL from devtools. Real protection needs DRM, which is deliberately out
 * of scope (see docs/architecture.md §7).
 */
export function LessonVideoPlayer({ courseSlug, lessonSlug }: LessonVideoPlayerProps) {
  const { data, isPending, isError, error } = useQuery<PlaybackTicket, ApiError>({
    queryKey: ["media", "playback", courseSlug, lessonSlug],
    queryFn: ({ signal }) => fetchPlaybackTicket(courseSlug, lessonSlug, signal),
    // Re-issue at 80% of the URL's life, so playback never trips over an
    // expired link mid-session.
    refetchInterval: (query) => {
      const ttl = query.state.data?.expires_in_seconds;
      return ttl !== undefined ? ttl * 0.8 * 1000 : false;
    },
    // A 404 here means "no video for this lesson" — a settled answer, not a
    // transient failure worth retrying.
    retry: (failureCount, queryError) =>
      queryError.isRetryable && failureCount < 2,
    staleTime: 0,
  });

  if (isPending) {
    return <Skeleton className="aspect-video w-full rounded-lg" />;
  }

  if (isError) {
    if (error.code === "NOT_FOUND") {
      return (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
            <VideoOff className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
            <p className="font-medium">No video yet</p>
            <p className="text-sm text-muted-foreground">
              The recording for this lesson has not been published.
            </p>
          </CardContent>
        </Card>
      );
    }
    return (
      <Alert variant="destructive" title="We could not load this video">
        {error.userMessage}
      </Alert>
    );
  }

  return (
    <video
      // Remounts when the signed URL rotates, so the element picks up the new
      // source instead of retrying the expired one.
      key={data.url}
      src={data.url}
      controls
      controlsList="nodownload"
      preload="metadata"
      playsInline
      className="aspect-video w-full rounded-lg bg-black"
    >
      {/* Captions land with the notes feature; the empty track keeps the
          element valid and signals the gap to assistive technology. */}
      <track kind="captions" label="Captions unavailable" />
      Your browser does not support embedded video.
    </video>
  );
}
