"""Automatic response-envelope wrapping.

Rule 8 says every API returns `{success, data, message}`. Two ways to achieve
that:

1. **Every handler builds the envelope itself.** One forgotten `SuccessResponse(...)`
   and a route silently ships a bare payload. The contract holds only as long as
   reviewer attention does.
2. **The route layer wraps it.** Handlers return domain objects and cannot opt out.

This module implements (2). A handler declares `response_model=SuccessResponse[X]`
and returns an `X`; the route wraps it. The OpenAPI schema still advertises the
full envelope, so generated clients and the docs stay accurate.

Note the absence of `from __future__ import annotations` in this module and in
the routers: FastAPI resolves handler type hints against the *defining module's*
globals. Because the wrapper below replaces the handler object, string
annotations would be evaluated in the wrong namespace. Keeping annotations as
real objects avoids that entirely.
"""

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from app.middleware.request_context import get_request_id
from app.schemas.common import SuccessResponse


@dataclass(frozen=True, slots=True)
class Enveloped:
    """Return this from a handler to set the envelope's `message` alongside data.

    Handlers that only need `data` should return the payload directly.
    """

    data: Any
    message: str = ""


def _returns_envelope(response_model: Any) -> bool:
    """True when the declared response model is a `SuccessResponse[...]`.

    Pydantic v2 materialises generic parameterisations as real subclasses, so a
    plain `issubclass` check is sufficient and needs no `typing` introspection.
    """
    return (
        response_model is not None
        and isinstance(response_model, type)
        and issubclass(response_model, SuccessResponse)
    )


def _build_envelope(result: Any) -> dict[str, Any]:
    """Wrap a handler result in the success envelope."""
    if isinstance(result, Enveloped):
        data, message = result.data, result.message
    else:
        data, message = result, ""

    body: dict[str, Any] = {"success": True, "data": data, "message": message}
    request_id = get_request_id()
    if request_id:
        body["meta"] = {"request_id": request_id}
    return body


def _wrap_endpoint(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Return an endpoint that envelopes its result.

    `functools.wraps` preserves `__wrapped__`, so `inspect.signature` still
    reports the original parameters and FastAPI's dependency injection is
    unaffected.
    """
    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def async_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return _build_envelope(await endpoint(*args, **kwargs))

        return async_wrapper

    @functools.wraps(endpoint)
    async def sync_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Sync handlers are offloaded so a blocking call cannot stall the loop —
        # matching how FastAPI would have run the unwrapped function.
        return _build_envelope(await run_in_threadpool(endpoint, *args, **kwargs))

    return sync_wrapper


class EnvelopedRoute(APIRoute):
    """An APIRoute that wraps handler results in the standard envelope.

    Routes whose `response_model` is not a `SuccessResponse[...]` pass through
    untouched, so a future streaming or file-download route is not forced into a
    JSON envelope it cannot satisfy.
    """

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        if _returns_envelope(kwargs.get("response_model")):
            endpoint = _wrap_endpoint(endpoint)
        super().__init__(path, endpoint, **kwargs)


def create_router(**kwargs: Any) -> APIRouter:
    """Build a router that envelopes its responses.

    Feature routers should use this instead of `APIRouter` directly.
    """
    kwargs.setdefault("route_class", EnvelopedRoute)
    return APIRouter(**kwargs)
