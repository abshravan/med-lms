"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { adminCourseKeys } from "@/features/courses/hooks/use-admin-courses";
import { courseKeys } from "@/features/courses/hooks/use-catalogue";
import type { LessonSummary } from "@/features/courses/types";
import { attachLessonVideo } from "@/features/media/api";
import { MediaUploader } from "@/features/media/components/media-uploader";
import type { MediaAsset } from "@/features/media/types";
import { ApiError } from "@/lib/api/errors";

export interface LessonVideoUploaderProps {
  courseId: string;
  lesson: LessonSummary;
}

/**
 * Upload and attach a video to one lesson.
 *
 * Upload and attachment are two server calls, not one: the asset must be
 * confirmed present in storage before anything may point at it. Doing them
 * together here means an author never sees a "ready" asset that is not actually
 * on the lesson.
 */
export function LessonVideoUploader({ courseId, lesson }: LessonVideoUploaderProps) {
  const queryClient = useQueryClient();
  const [attachError, setAttachError] = React.useState<string | null>(null);
  const [justAttached, setJustAttached] = React.useState(false);

  const handleUploaded = async (asset: MediaAsset) => {
    setAttachError(null);
    try {
      await attachLessonVideo(lesson.id, asset.id);
      setJustAttached(true);
      // Refresh both views: the editor's outline and anything a student would
      // see, since attaching changes what the lesson page can play.
      void queryClient.invalidateQueries({ queryKey: adminCourseKeys.detail(courseId) });
      void queryClient.invalidateQueries({ queryKey: courseKeys.all });
    } catch (cause) {
      // The upload succeeded; only the attachment failed. Saying so tells the
      // author to retry the attach rather than re-upload a large file.
      setAttachError(
        cause instanceof ApiError
          ? `Uploaded, but could not attach: ${cause.userMessage}`
          : "Uploaded, but could not attach it to the lesson.",
      );
    }
  };

  return (
    <div className="pl-4">
      <MediaUploader
        kind="lesson_video"
        label={justAttached ? "Replace video" : "Upload video"}
        onUploaded={handleUploaded}
      />
      {justAttached && attachError === null ? (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          Video attached to “{lesson.title}”.
        </p>
      ) : null}
      {attachError !== null ? (
        <Alert variant="destructive" className="mt-2">
          {attachError}
        </Alert>
      ) : null}
    </div>
  );
}
