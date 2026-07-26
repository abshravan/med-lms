"""Centralised exception handling.

Every error response in the application is produced here. Routes raise domain
exceptions and never build an error body, which is what guarantees the envelope
contract holds across the whole API — including for errors raised inside
dependencies, before any route code runs.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError, ErrorCode
from app.core.logging import get_logger
from app.middleware.request_context import REQUEST_ID_HEADER, request_id_of
from app.schemas.common import error_envelope

logger = get_logger(__name__)

# Starlette status code → stable application error code.
_STATUS_TO_CODE = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.UPSTREAM_UNAVAILABLE,
}


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    details: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build an enveloped error response.

    Single construction point for every error body, so the correlation id is
    always attached — both in `meta` and as a response header. The header matters
    on 5xx responses, which are produced outside the request middleware and would
    otherwise carry no id at all.
    """
    request_id = request_id_of(request)
    response = JSONResponse(
        status_code=status_code,
        content=error_envelope(
            code=code,
            message=message,
            details=details,
            request_id=request_id or None,
        ),
        headers=headers,
    )
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to the application."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Expected domain failures."""
        logger.info(
            "app_error",
            code=exc.code.value,
            status_code=exc.status_code,
            detail=exc.message,
        )
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Pydantic request validation failures, flattened to field errors."""
        return _error_response(
            request,
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="The submitted data is invalid.",
            details=[
                {
                    "field": _field_path(error.get("loc", ())),
                    "message": str(error.get("msg", "Invalid value.")),
                }
                for error in exc.errors()
            ],
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Framework-raised HTTP errors (404 on an unknown path, 405, ...).

        Mapped into the envelope so even a typo'd URL returns the documented
        shape rather than Starlette's default `{"detail": ...}`.
        """
        return _error_response(
            request,
            status_code=exc.status_code,
            code=_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR),
            message=str(exc.detail) if exc.detail else "Request could not be completed.",
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Anything unhandled is a bug.

        The exception is logged with a stack trace; the client gets a generic
        message plus the request id. Internal detail is never echoed to the
        client — that is how stack traces and SQL end up in bug-bounty reports.
        """
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return _error_response(
            request,
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred. Please try again.",
        )


def _field_path(location: object) -> str:
    """Render a Pydantic error location as a dotted path.

    The leading `body` / `query` segment is dropped so the field name matches what
    the client actually submitted, which lets the frontend map errors straight
    onto form fields.
    """
    if not isinstance(location, (list, tuple)):
        return str(location)
    parts = [str(part) for part in location]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    return ".".join(parts) if parts else "root"
