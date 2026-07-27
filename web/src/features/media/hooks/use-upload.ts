"use client";

import * as React from "react";

import {
  confirmUpload,
  requestUploadTicket,
  uploadDirect,
} from "@/features/media/api";
import { validateFile, type MediaAsset, type MediaKind } from "@/features/media/types";
import { ApiError } from "@/lib/api/errors";

/**
 * The upload is a three-step sequence, and the UI has to say which step failed:
 * "we could not reach the server", "the upload itself failed", and "the file did
 * not arrive" call for different actions from the author.
 */
export type UploadPhase = "idle" | "requesting" | "uploading" | "confirming" | "done" | "error";

export interface UploadState {
  phase: UploadPhase;
  /** 0–1, only meaningful during `uploading`. */
  progress: number;
  error: string | null;
  asset: MediaAsset | null;
}

const INITIAL: UploadState = {
  phase: "idle",
  progress: 0,
  error: null,
  asset: null,
};

export interface UseUploadResult extends UploadState {
  upload: (file: File) => Promise<MediaAsset | null>;
  cancel: () => void;
  reset: () => void;
  isBusy: boolean;
}

/**
 * Direct-to-storage upload with progress.
 *
 * Deliberately *not* a TanStack mutation: the interesting state here is a
 * three-phase progress machine driven by XHR events, not a single
 * pending/success/error flag, and there is no server state to cache. Forcing it
 * into `useMutation` would mean tracking the phase in separate state anyway.
 */
export function useUpload(kind: MediaKind): UseUploadResult {
  const [state, setState] = React.useState<UploadState>(INITIAL);
  const abortRef = React.useRef<AbortController | null>(null);
  // Guards against setting state after the component unmounts mid-upload —
  // uploads outlive navigation more often than most requests.
  const mountedRef = React.useRef(true);

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const update = React.useCallback((patch: Partial<UploadState>) => {
    if (mountedRef.current) {
      setState((current) => ({ ...current, ...patch }));
    }
  }, []);

  const reset = React.useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (mountedRef.current) {
      setState(INITIAL);
    }
  }, []);

  const cancel = React.useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    update({ phase: "idle", progress: 0 });
  }, [update]);

  const upload = React.useCallback(
    async (file: File): Promise<MediaAsset | null> => {
      const check = validateFile(file, kind);
      if (!check.ok) {
        // Rejected before any request: no point burning a ticket on a file the
        // server will refuse.
        update({ phase: "error", error: check.message, progress: 0 });
        return null;
      }

      const controller = new AbortController();
      abortRef.current = controller;
      update({ phase: "requesting", progress: 0, error: null, asset: null });

      try {
        const ticket = await requestUploadTicket({
          kind,
          filename: file.name,
          content_type: file.type,
          size_bytes: file.size,
        });

        update({ phase: "uploading" });
        await uploadDirect({
          ticket,
          file,
          onProgress: (fraction) => update({ progress: fraction }),
          signal: controller.signal,
        });

        update({ phase: "confirming", progress: 1 });
        // Confirmation is what makes the asset usable: the server HEADs the
        // object before trusting that the upload happened.
        const asset = await confirmUpload(ticket.asset_id);

        update({ phase: "done", asset, error: null });
        return asset;
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === "AbortError") {
          update({ phase: "idle", progress: 0 });
          return null;
        }
        update({
          phase: "error",
          error:
            cause instanceof ApiError
              ? cause.userMessage
              : cause instanceof Error
                ? cause.message
                : "The upload failed. Please try again.",
        });
        return null;
      } finally {
        abortRef.current = null;
      }
    },
    [kind, update],
  );

  return {
    ...state,
    upload,
    cancel,
    reset,
    isBusy:
      state.phase === "requesting" ||
      state.phase === "uploading" ||
      state.phase === "confirming",
  };
}
