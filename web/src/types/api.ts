/**
 * The domain API contract, mirrored in TypeScript.
 *
 * These types correspond one-to-one with `backend/app/schemas/common.py` and
 * `backend/app/schemas/auth.py`. They are hand-written rather than generated
 * because there is exactly one endpoint group so far and codegen would be more
 * machinery than the problem warrants.
 *
 * The moment a second feature lands, generate them from the OpenAPI schema
 * (`openapi-typescript`) instead — hand-maintaining a growing contract in two
 * languages is how the two drift apart. Recorded as follow-up work in
 * docs/features/authentication.md.
 */

/** Stable error codes from `backend/app/core/exceptions.py::ErrorCode`. */
export type ApiErrorCode =
  | "VALIDATION_ERROR"
  | "UNAUTHENTICATED"
  | "TOKEN_EXPIRED"
  | "TOKEN_INVALID"
  | "SESSION_REVOKED"
  | "EMAIL_NOT_VERIFIED"
  | "ACCOUNT_BANNED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "CONFLICT"
  | "RATE_LIMITED"
  | "UPSTREAM_UNAVAILABLE"
  | "INTERNAL_ERROR";

export interface ApiFieldError {
  field: string;
  message: string;
}

export interface ApiResponseMeta {
  request_id: string;
}

export interface ApiSuccessResponse<TData> {
  success: true;
  data: TData;
  message: string;
  meta?: ApiResponseMeta;
}

export interface ApiErrorResponse {
  success: false;
  data: null;
  message: string;
  error: {
    code: ApiErrorCode;
    details?: ApiFieldError[];
  };
  meta?: ApiResponseMeta;
}

export type ApiResponse<TData> = ApiSuccessResponse<TData> | ApiErrorResponse;

/** Narrowing helper so callers never inspect `success` by hand. */
export function isApiErrorResponse(
  body: ApiResponse<unknown>,
): body is ApiErrorResponse {
  return body.success === false;
}
