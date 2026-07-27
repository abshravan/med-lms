"use client";

import { Upload, X } from "lucide-react";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useUpload } from "@/features/media/hooks/use-upload";
import {
  acceptAttribute,
  formatBytes,
  MAX_BYTES,
  type MediaAsset,
  type MediaKind,
} from "@/features/media/types";

export interface MediaUploaderProps {
  kind: MediaKind;
  label: string;
  /** Called once the asset is confirmed ready. */
  onUploaded: (asset: MediaAsset) => void | Promise<void>;
  disabled?: boolean;
}

const PHASE_LABELS: Record<string, string> = {
  requesting: "Preparing upload…",
  uploading: "Uploading…",
  confirming: "Finishing…",
};

/**
 * File picker with direct-to-storage upload and progress.
 *
 * The phase is surfaced rather than a single spinner because the three steps
 * fail for different reasons and an author needs to know which one to retry —
 * "preparing" failing is a server problem; "uploading" failing is usually the
 * connection or an expired link.
 */
export function MediaUploader({
  kind,
  label,
  onUploaded,
  disabled = false,
}: MediaUploaderProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const { upload, cancel, reset, phase, progress, error, isBusy } = useUpload(kind);
  const inputId = React.useId();

  const handleChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Clear immediately so re-picking the same file still fires `change`.
    event.target.value = "";
    if (file === undefined) {
      return;
    }
    const asset = await upload(file);
    if (asset !== null) {
      await onUploaded(asset);
      reset();
    }
  };

  return (
    <div className="space-y-3">
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={acceptAttribute(kind)}
        onChange={(event) => void handleChange(event)}
        disabled={disabled || isBusy}
        className="sr-only"
      />

      {!isBusy ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            onClick={() => inputRef.current?.click()}
          >
            <Upload className="h-4 w-4" aria-hidden="true" />
            {label}
          </Button>
          <p className="text-xs text-muted-foreground">
            Up to {formatBytes(MAX_BYTES[kind])}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">
              {PHASE_LABELS[phase] ?? "Working…"}
            </p>
            <Button type="button" variant="ghost" size="sm" onClick={cancel}>
              <X className="h-4 w-4" aria-hidden="true" />
              Cancel
            </Button>
          </div>
          <Progress
            value={phase === "uploading" ? Math.round(progress * 100) : undefined}
            label={PHASE_LABELS[phase] ?? "Working"}
          />
          {phase === "uploading" ? (
            <p className="text-xs text-muted-foreground">
              {Math.round(progress * 100)}% — leaving this page will cancel the upload.
            </p>
          ) : null}
        </div>
      )}

      {error !== null ? (
        <Alert variant="destructive">
          {error}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={reset}
          >
            Dismiss
          </Button>
        </Alert>
      ) : null}
    </div>
  );
}
