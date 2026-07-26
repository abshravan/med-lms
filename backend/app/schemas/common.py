"""The API response envelope.

Rule 8 of the project charter: *every* API returns a consistent response. This
module is the single definition of that shape. Routers return domain payloads;
the envelope is applied here and in the exception handlers, never hand-rolled
in a route.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import ErrorCode

DataT = TypeVar("DataT")


class ResponseMeta(BaseModel):
    """Envelope metadata attached to every response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(description="Correlation id, echoed in the X-Request-ID header.")


class FieldError(BaseModel):
    """A single field-level validation failure."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="Dotted path to the offending field.")
    message: str = Field(description="Why this field was rejected.")


class ErrorDetail(BaseModel):
    """Machine-readable error information."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    details: list[FieldError] | None = None


class SuccessResponse(BaseModel, Generic[DataT]):
    """Envelope for a successful response."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    data: DataT
    message: str = ""
    meta: ResponseMeta | None = None


class ErrorResponse(BaseModel):
    """Envelope for a failed response.

    `data` is always present and always null, so clients can rely on the key
    existing regardless of outcome.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = False
    data: None = None
    message: str
    error: ErrorDetail
    meta: ResponseMeta | None = None


class PaginationMeta(BaseModel):
    """Cursor pagination metadata.

    Cursor- rather than offset-based: at 100k users, `OFFSET 50000` degrades and
    rows shift under the reader between pages. Defined now so the first paginated
    feature does not invent its own shape.
    """

    model_config = ConfigDict(extra="forbid")

    next_cursor: str | None = None
    has_more: bool = False
    limit: int


class Page(BaseModel, Generic[DataT]):
    """A page of items, used as the `data` of a SuccessResponse."""

    model_config = ConfigDict(extra="forbid")

    items: list[DataT]
    pagination: PaginationMeta


def envelope(
    data: Any,
    *,
    message: str = "",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a success envelope as a plain dict.

    Used by the response-wrapping layer. Route handlers should prefer returning
    typed models and letting the wrapper do this.
    """
    body: dict[str, Any] = {"success": True, "data": data, "message": message}
    if request_id is not None:
        body["meta"] = {"request_id": request_id}
    return body


def error_envelope(
    *,
    code: ErrorCode,
    message: str,
    details: list[dict[str, str]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build an error envelope as a plain dict."""
    error: dict[str, Any] = {"code": code.value}
    if details:
        error["details"] = details
    body: dict[str, Any] = {
        "success": False,
        "data": None,
        "message": message,
        "error": error,
    }
    if request_id is not None:
        body["meta"] = {"request_id": request_id}
    return body
