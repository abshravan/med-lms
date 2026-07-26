"""Request correlation middleware.

Assigns every request an id, binds it to the logging context so all downstream
log lines carry it, echoes it in `X-Request-ID`, and puts it in the response
envelope's `meta`. When a student reports a failure, the id in the UI's error
toast is enough to find every log line for that request.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_STATE_KEY = "request_id"

# Read by the envelope wrapper, which does not have the Request object to hand.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Return the current request's correlation id, or "" outside a request."""
    return request_id_ctx.get()


def request_id_of(request: Request) -> str:
    """Return the correlation id for a request, preferring `request.state`.

    Exception handlers must use this rather than `get_request_id()`. Starlette's
    `ServerErrorMiddleware` — which invokes the catch-all `Exception` handler —
    sits *outside* this middleware, so by the time it runs the context variable
    has already been reset. `request.state` survives, which keeps the id present
    on 500 responses, exactly where it is most needed for debugging.
    """
    state_value = getattr(request.state, REQUEST_ID_STATE_KEY, "")
    if isinstance(state_value, str) and state_value:
        return state_value
    return request_id_ctx.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id and access log to every request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Honour an upstream id when present so traces span the whole edge → API
        # path, but never trust its shape.
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _is_safe_request_id(incoming) else str(uuid.uuid4())

        token = request_id_ctx.set(request_id)
        # Also stashed on the request so handlers running outside this middleware
        # can still correlate — see `request_id_of`.
        setattr(request.state, REQUEST_ID_STATE_KEY, request_id)
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers own the response body; this only records
            # timing before re-raising into them.
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        finally:
            request_id_ctx.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response


def _is_safe_request_id(value: str) -> bool:
    """Accept only short, printable, delimiter-free ids to prevent log injection."""
    return (
        0 < len(value) <= 64
        and value.isprintable()
        and all(char not in value for char in "\r\n \t")
    )
