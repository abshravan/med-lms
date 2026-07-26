/**
 * Normalised API errors.
 *
 * Everything that can go wrong when calling the domain API becomes an `ApiError`:
 * a domain failure, a network failure, or an unparseable response. That means UI
 * code has exactly one error shape to handle, and the difference between "server
 * said no" and "the wifi dropped" is a property rather than a different type.
 */

import type { ApiErrorCode, ApiFieldError } from "@/types/api";

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly fieldErrors: ApiFieldError[];
  readonly requestId: string | null;

  constructor(params: {
    message: string;
    code: ApiErrorCode;
    status: number;
    fieldErrors?: ApiFieldError[];
    requestId?: string | null;
  }) {
    super(params.message);
    this.name = "ApiError";
    this.code = params.code;
    this.status = params.status;
    this.fieldErrors = params.fieldErrors ?? [];
    this.requestId = params.requestId ?? null;
  }

  /** True when re-authenticating could plausibly fix this. */
  get isAuthError(): boolean {
    return (
      this.code === "UNAUTHENTICATED" ||
      this.code === "TOKEN_EXPIRED" ||
      this.code === "TOKEN_INVALID" ||
      this.code === "SESSION_REVOKED"
    );
  }

  /** True when the user must verify their email before proceeding. */
  get requiresEmailVerification(): boolean {
    return this.code === "EMAIL_NOT_VERIFIED";
  }

  /**
   * True when a retry is worth attempting.
   *
   * Note that 4xx codes are absent: retrying a validation error just produces the
   * same validation error.
   */
  get isRetryable(): boolean {
    return (
      this.code === "UPSTREAM_UNAVAILABLE" ||
      this.code === "INTERNAL_ERROR" ||
      this.status === 0 ||
      this.status >= 500
    );
  }

  /** A message safe and useful to show a student. */
  get userMessage(): string {
    switch (this.code) {
      case "VALIDATION_ERROR":
        return this.fieldErrors.length > 0
          ? this.fieldErrors[0]!.message
          : "Please check the details you entered.";
      case "UNAUTHENTICATED":
      case "TOKEN_EXPIRED":
      case "TOKEN_INVALID":
      case "SESSION_REVOKED":
        return "Your session has ended. Please sign in again.";
      case "EMAIL_NOT_VERIFIED":
        return "Please verify your email address to continue.";
      case "ACCOUNT_BANNED":
        return this.message;
      case "FORBIDDEN":
        return "You do not have access to this.";
      case "NOT_FOUND":
        return "We could not find what you were looking for.";
      case "RATE_LIMITED":
        return "Too many attempts. Please wait a moment and try again.";
      case "UPSTREAM_UNAVAILABLE":
        return "A service we depend on is temporarily unavailable. Please try again.";
      default:
        return "Something went wrong on our end. Please try again.";
    }
  }

  /** A network or CORS failure — the request never got a response. */
  static network(cause: unknown): ApiError {
    return new ApiError({
      message:
        cause instanceof Error ? cause.message : "The request could not be sent.",
      code: "UPSTREAM_UNAVAILABLE",
      status: 0,
    });
  }

  /** A response that was not the documented envelope. */
  static malformed(status: number, requestId: string | null): ApiError {
    return new ApiError({
      message: "The server returned an unexpected response.",
      code: "INTERNAL_ERROR",
      status,
      requestId,
    });
  }
}

/** Map field errors onto the shape `react-hook-form`'s `setError` expects. */
export function toFormErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) {
    return {};
  }
  return Object.fromEntries(
    error.fieldErrors.map((fieldError) => [fieldError.field, fieldError.message]),
  );
}
