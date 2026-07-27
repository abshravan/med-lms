/**
 * Upload flow tests.
 *
 * The three-phase sequence (ticket → direct PUT → confirm) is the part users
 * feel when it goes wrong, and the part hardest to exercise by hand: a failed
 * confirm looks identical to a failed upload unless the phases are tracked
 * separately.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import {
  ACCEPTED_TYPES,
  MAX_BYTES,
  formatBytes,
  validateFile,
} from "@/features/media/types";

const requestUploadTicket = vi.fn();
const confirmUpload = vi.fn();
const uploadDirect = vi.fn();

vi.mock("@/features/media/api", () => ({
  requestUploadTicket: (...args: unknown[]) => requestUploadTicket(...args),
  confirmUpload: (...args: unknown[]) => confirmUpload(...args),
  uploadDirect: (...args: unknown[]) => uploadDirect(...args),
}));

const { useUpload } = await import("@/features/media/hooks/use-upload");

function makeFile(
  name = "lecture.mp4",
  type = "video/mp4",
  size = 1024,
): File {
  const file = new File(["x"], name, { type });
  // `File` size is derived from its parts; override so tests can express any
  // size without allocating it.
  Object.defineProperty(file, "size", { value: size });
  return file;
}

const TICKET = {
  asset_id: "asset-1",
  upload_url: "https://storage.test/put",
  method: "PUT",
  headers: { "Content-Type": "video/mp4" },
  expires_in_seconds: 900,
  storage_key: "lesson_video/2026/07/abc.mp4",
};

const READY_ASSET = {
  id: "asset-1",
  kind: "lesson_video" as const,
  status: "ready" as const,
  original_filename: "lecture.mp4",
  content_type: "video/mp4",
  size_bytes: 1024,
  confirmed_at: "2026-07-27T00:00:00Z",
  created_at: "2026-07-27T00:00:00Z",
};

beforeEach(() => {
  requestUploadTicket.mockReset();
  confirmUpload.mockReset();
  uploadDirect.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("validateFile", () => {
  it("accepts a permitted video", () => {
    expect(validateFile(makeFile(), "lesson_video").ok).toBe(true);
  });

  it("rejects a disallowed type", () => {
    const result = validateFile(makeFile("evil.html", "text/html"), "lesson_video");

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("not accepted");
    }
  });

  it("rejects a file over the per-kind ceiling", () => {
    const oversized = makeFile("huge.png", "image/png", MAX_BYTES.course_cover + 1);

    expect(validateFile(oversized, "course_cover").ok).toBe(false);
  });

  it("applies the kind's own ceiling, not a global one", () => {
    // 50 MB is fine for a video and far too large for a cover image.
    const fifty = 50 * 1024 ** 2;

    expect(validateFile(makeFile("v.mp4", "video/mp4", fifty), "lesson_video").ok).toBe(
      true,
    );
    expect(validateFile(makeFile("c.png", "image/png", fifty), "course_cover").ok).toBe(
      false,
    );
  });

  it("rejects an empty file", () => {
    expect(validateFile(makeFile("empty.mp4", "video/mp4", 0), "lesson_video").ok).toBe(
      false,
    );
  });

  it("mirrors the server's allowlist", () => {
    // Drift here means the client accepts a file the server will reject.
    expect(ACCEPTED_TYPES.lesson_attachment).toEqual(["application/pdf"]);
    expect(ACCEPTED_TYPES.course_cover).not.toContain("image/svg+xml");
  });
});

describe("formatBytes", () => {
  it.each([
    [null, "—"],
    [0, "—"],
    [512, "512 B"],
    [2048, "2 KB"],
    [5 * 1024 ** 2, "5 MB"],
    [Math.round(1.5 * 1024 ** 3), "1.5 GB"],
  ])("formats %s as %s", (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});

describe("useUpload", () => {
  it("runs ticket → upload → confirm and reports the asset", async () => {
    requestUploadTicket.mockResolvedValue(TICKET);
    uploadDirect.mockResolvedValue(undefined);
    confirmUpload.mockResolvedValue(READY_ASSET);

    const { result } = renderHook(() => useUpload("lesson_video"));

    let returned: unknown;
    await act(async () => {
      returned = await result.current.upload(makeFile());
    });

    expect(returned).toEqual(READY_ASSET);
    expect(result.current.phase).toBe("done");
    expect(result.current.asset).toEqual(READY_ASSET);

    // The declared size comes from the file itself, not a guess.
    expect(requestUploadTicket).toHaveBeenCalledWith({
      kind: "lesson_video",
      filename: "lecture.mp4",
      content_type: "video/mp4",
      size_bytes: 1024,
    });
    // Confirmation is a separate step — the server must verify the object.
    expect(confirmUpload).toHaveBeenCalledWith("asset-1");
  });

  it("sends the ticket's headers verbatim, because they are signed", async () => {
    requestUploadTicket.mockResolvedValue(TICKET);
    uploadDirect.mockResolvedValue(undefined);
    confirmUpload.mockResolvedValue(READY_ASSET);

    const { result } = renderHook(() => useUpload("lesson_video"));
    await act(async () => {
      await result.current.upload(makeFile());
    });

    const passed = uploadDirect.mock.calls[0]![0] as { ticket: typeof TICKET };
    expect(passed.ticket.headers).toEqual({ "Content-Type": "video/mp4" });
  });

  it("rejects an invalid file without requesting a ticket", async () => {
    const { result } = renderHook(() => useUpload("lesson_video"));

    await act(async () => {
      await result.current.upload(makeFile("doc.pdf", "application/pdf"));
    });

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toContain("not accepted");
    // No point burning a presigned URL on a file the server will refuse.
    expect(requestUploadTicket).not.toHaveBeenCalled();
  });

  it("reports progress during the upload", async () => {
    requestUploadTicket.mockResolvedValue(TICKET);
    confirmUpload.mockResolvedValue(READY_ASSET);
    uploadDirect.mockImplementation(
      async (options: { onProgress?: (f: number) => void }) => {
        options.onProgress?.(0.25);
        options.onProgress?.(0.75);
      },
    );

    const { result } = renderHook(() => useUpload("lesson_video"));
    await act(async () => {
      await result.current.upload(makeFile());
    });

    // Snaps to 1 once the bytes are away and confirmation begins.
    expect(result.current.progress).toBe(1);
  });

  it("distinguishes a failed upload from a failed confirmation", async () => {
    requestUploadTicket.mockResolvedValue(TICKET);
    uploadDirect.mockRejectedValue(new Error("Upload failed (403)."));

    const { result } = renderHook(() => useUpload("lesson_video"));
    await act(async () => {
      await result.current.upload(makeFile());
    });

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toContain("403");
    // Never confirmed, because the bytes never arrived.
    expect(confirmUpload).not.toHaveBeenCalled();
  });

  it("surfaces a rejected confirmation in the user's language", async () => {
    requestUploadTicket.mockResolvedValue(TICKET);
    uploadDirect.mockResolvedValue(undefined);
    confirmUpload.mockRejectedValue(
      new ApiError({
        message: "No uploaded file was found for this upload.",
        code: "CONFLICT",
        status: 409,
      }),
    );

    const { result } = renderHook(() => useUpload("lesson_video"));
    await act(async () => {
      await result.current.upload(makeFile());
    });

    expect(result.current.phase).toBe("error");
    expect(result.current.error).not.toContain("undefined");
  });

  it("treats an abort as a return to idle, not a failure", async () => {
    requestUploadTicket.mockResolvedValue(TICKET);
    uploadDirect.mockRejectedValue(new DOMException("aborted", "AbortError"));

    const { result } = renderHook(() => useUpload("lesson_video"));
    await act(async () => {
      await result.current.upload(makeFile());
    });

    expect(result.current.phase).toBe("idle");
    expect(result.current.error).toBeNull();
  });

  it("clears state on reset", async () => {
    requestUploadTicket.mockResolvedValue(TICKET);
    uploadDirect.mockResolvedValue(undefined);
    confirmUpload.mockResolvedValue(READY_ASSET);

    const { result } = renderHook(() => useUpload("lesson_video"));
    await act(async () => {
      await result.current.upload(makeFile());
    });
    act(() => result.current.reset());

    await waitFor(() => {
      expect(result.current.phase).toBe("idle");
      expect(result.current.asset).toBeNull();
    });
  });
});
