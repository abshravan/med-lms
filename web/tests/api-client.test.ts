/**
 * API client tests.
 *
 * The token lifecycle is the part of the frontend most likely to break in a way
 * users notice (spurious sign-outs, redirect loops), and the part hardest to
 * verify by clicking around. So it is pinned here: caching, single-flight
 * refresh, one bounded retry, and error normalisation.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest, clearCachedAccessToken } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { ApiErrorCode } from "@/types/api";

const API_BASE = "http://api.test";

/** Build a JWT-shaped string with a real `exp`. Never verified client-side. */
function makeToken(expiresInSeconds: number): string {
  const payload = {
    sub: "user_1",
    exp: Math.floor(Date.now() / 1000) + expiresInSeconds,
  };
  const encode = (value: object): string =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "ES256" })}.${encode(payload)}.signature`;
}

function successBody(data: unknown) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "X-Request-ID": "req-1" }),
    json: async () => ({ success: true, data, message: "" }),
  } as Response;
}

function errorBody(status: number, code: ApiErrorCode, message = "nope", details?: unknown) {
  return {
    ok: false,
    status,
    headers: new Headers({ "X-Request-ID": "req-err" }),
    json: async () => ({
      success: false,
      data: null,
      message,
      error: { code, ...(details !== undefined ? { details } : {}) },
      meta: { request_id: "req-err" },
    }),
  } as Response;
}

function tokenBody(token: string) {
  return {
    ok: true,
    status: 200,
    headers: new Headers(),
    json: async () => ({ token }),
  } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clearCachedAccessToken();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  clearCachedAccessToken();
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("attaches a bearer token and unwraps the envelope", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(successBody({ user_id: "user_1" }));

    const result = await apiRequest<{ user_id: string }>("/api/v1/auth/me");

    // The caller receives `data`, not the envelope.
    expect(result).toEqual({ user_id: "user_1" });

    const [url, init] = fetchMock.mock.calls[1]!;
    expect(url).toBe(`${API_BASE}/api/v1/auth/me`);
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toMatch(/^Bearer /);
  });

  it("reuses a cached token across requests", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValue(successBody({ ok: true }));

    await apiRequest("/api/v1/auth/me");
    await apiRequest("/api/v1/auth/me");
    await apiRequest("/api/v1/auth/me");

    const tokenCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/auth/token");
    expect(tokenCalls).toHaveLength(1);
  });

  it("refetches a token that is about to expire", async () => {
    // Inside the 60s refresh margin, so it must not be reused.
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(30)))
      .mockResolvedValueOnce(successBody({ ok: true }))
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(successBody({ ok: true }));

    await apiRequest("/api/v1/auth/me");
    await apiRequest("/api/v1/auth/me");

    const tokenCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/auth/token");
    expect(tokenCalls).toHaveLength(2);
  });

  it("collapses concurrent requests into a single token fetch", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === "/api/auth/token"
        ? tokenBody(makeToken(900))
        : successBody({ ok: true }),
    );

    // A dashboard firing several queries at once must not mint several tokens.
    await Promise.all([
      apiRequest("/api/v1/a"),
      apiRequest("/api/v1/b"),
      apiRequest("/api/v1/c"),
    ]);

    const tokenCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/auth/token");
    expect(tokenCalls).toHaveLength(1);
  });

  it("retries exactly once with a fresh token after TOKEN_EXPIRED", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(errorBody(401, "TOKEN_EXPIRED"))
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(successBody({ recovered: true }));

    const result = await apiRequest<{ recovered: boolean }>("/api/v1/auth/me");

    expect(result).toEqual({ recovered: true });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("gives up after one retry rather than looping", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(errorBody(401, "TOKEN_EXPIRED"))
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(errorBody(401, "TOKEN_EXPIRED"));

    await expect(apiRequest("/api/v1/auth/me")).rejects.toBeInstanceOf(ApiError);

    // Two attempts, not an unbounded spin.
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("does not retry a SESSION_REVOKED response", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(errorBody(401, "SESSION_REVOKED"));

    // A revoked session cannot be fixed by a new token — retrying would be waste.
    await expect(apiRequest("/api/v1/auth/me")).rejects.toMatchObject({
      code: "SESSION_REVOKED",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("fails fast when there is no session at all", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: new Headers(),
      json: async () => ({}),
    } as Response);

    await expect(apiRequest("/api/v1/auth/me")).rejects.toMatchObject({
      code: "UNAUTHENTICATED",
    });
    // No pointless call to the domain API without a token.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("skips auth entirely when asked", async () => {
    fetchMock.mockResolvedValueOnce(successBody({ status: "ok" }));

    await apiRequest("/health", { skipAuth: true });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe(`${API_BASE}/health`);
  });

  it("surfaces field errors from a validation failure", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockResolvedValueOnce(
        errorBody(422, "VALIDATION_ERROR", "The submitted data is invalid.", [
          { field: "year_of_study", message: "Input should be less than or equal to 10" },
        ]),
      );

    try {
      await apiRequest("/api/v1/auth/me", { method: "PATCH", body: { year_of_study: 99 } });
      expect.unreachable("should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.fieldErrors).toHaveLength(1);
      expect(apiError.fieldErrors[0]?.field).toBe("year_of_study");
      expect(apiError.requestId).toBe("req-err");
    }
  });

  it("converts a network failure into a retryable ApiError", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    try {
      await apiRequest("/api/v1/auth/me");
      expect.unreachable("should have thrown");
    } catch (error) {
      const apiError = error as ApiError;
      expect(apiError.status).toBe(0);
      expect(apiError.isRetryable).toBe(true);
    }
  });

  it("propagates an abort instead of reporting it as a failure", async () => {
    fetchMock
      .mockResolvedValueOnce(tokenBody(makeToken(900)))
      .mockRejectedValueOnce(new DOMException("aborted", "AbortError"));

    await expect(apiRequest("/api/v1/auth/me")).rejects.toBeInstanceOf(DOMException);
  });

  it("treats a non-envelope response as an internal error", async () => {
    fetchMock.mockResolvedValueOnce(tokenBody(makeToken(900))).mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);

    await expect(apiRequest("/api/v1/auth/me")).rejects.toMatchObject({
      code: "INTERNAL_ERROR",
    });
  });
});

describe("ApiError", () => {
  it("classifies auth errors", () => {
    for (const code of [
      "UNAUTHENTICATED",
      "TOKEN_EXPIRED",
      "TOKEN_INVALID",
      "SESSION_REVOKED",
    ] as const) {
      expect(new ApiError({ message: "", code, status: 401 }).isAuthError).toBe(true);
    }
    expect(
      new ApiError({ message: "", code: "FORBIDDEN", status: 403 }).isAuthError,
    ).toBe(false);
  });

  it("does not mark client errors as retryable", () => {
    expect(
      new ApiError({ message: "", code: "VALIDATION_ERROR", status: 422 }).isRetryable,
    ).toBe(false);
    expect(
      new ApiError({ message: "", code: "FORBIDDEN", status: 403 }).isRetryable,
    ).toBe(false);
  });

  it("prefers a field message for validation errors", () => {
    const error = new ApiError({
      message: "The submitted data is invalid.",
      code: "VALIDATION_ERROR",
      status: 422,
      fieldErrors: [{ field: "timezone", message: "Not a recognised IANA timezone." }],
    });
    expect(error.userMessage).toBe("Not a recognised IANA timezone.");
  });

  it("never exposes a raw internal message to the user", () => {
    const error = new ApiError({
      message: "psycopg2.ProgrammingError: relation does not exist",
      code: "INTERNAL_ERROR",
      status: 500,
    });
    expect(error.userMessage).not.toContain("psycopg2");
  });
});
