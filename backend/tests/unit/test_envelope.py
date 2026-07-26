"""Tests for the response-envelope contract.

Rule 8 says every API returns the same shape. These tests assert that the
*mechanism* enforcing it works, so a future feature cannot regress the contract
by simply forgetting to wrap a response.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.envelope import Enveloped, create_router
from app.core.exceptions import ConflictError, NotFoundError
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.schemas.common import SuccessResponse


class Widget(BaseModel):
    """Trivial payload used to exercise the wrapper."""

    name: str


@pytest.fixture
def contract_app() -> FastAPI:
    """A minimal app exercising the envelope machinery in isolation."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    router = create_router()

    @router.get("/plain", response_model=SuccessResponse[Widget])
    async def plain() -> Widget:
        return Widget(name="scalpel")

    @router.get("/with-message", response_model=SuccessResponse[Widget])
    async def with_message() -> Enveloped:
        return Enveloped(data=Widget(name="suture"), message="Created for you.")

    @router.get("/sync", response_model=SuccessResponse[Widget])
    def sync_handler() -> Widget:
        return Widget(name="forceps")

    @router.get("/boom", response_model=SuccessResponse[Widget])
    async def boom() -> Widget:
        raise NotFoundError("No such widget.")

    @router.get("/conflict", response_model=SuccessResponse[Widget])
    async def conflict() -> Widget:
        raise ConflictError()

    @router.get("/unhandled", response_model=SuccessResponse[Widget])
    async def unhandled() -> Widget:
        raise RuntimeError("a secret internal detail")

    app.include_router(router)
    return app


@pytest.fixture
async def contract_client(contract_app: FastAPI):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=contract_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_handler_result_is_wrapped(contract_client: AsyncClient) -> None:
    """A handler returns a domain model; the client sees the envelope."""
    response = await contract_client.get("/plain")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"name": "scalpel"},
        "message": "",
        "meta": {"request_id": response.headers["X-Request-ID"]},
    }


async def test_handler_can_set_a_message(contract_client: AsyncClient) -> None:
    response = await contract_client.get("/with-message")

    body = response.json()
    assert body["message"] == "Created for you."
    assert body["data"] == {"name": "suture"}


async def test_sync_handlers_are_wrapped_too(contract_client: AsyncClient) -> None:
    """Sync handlers must not bypass the envelope."""
    response = await contract_client.get("/sync")

    assert response.json()["data"] == {"name": "forceps"}
    assert response.json()["success"] is True


async def test_openapi_advertises_the_envelope(contract_app: FastAPI) -> None:
    """Generated clients must see the wrapped shape, not the bare payload.

    Wrapping at the route layer would be a false economy if it made the schema
    lie about the response.
    """
    schema = contract_app.openapi()
    ref = schema["paths"]["/plain"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    model_name = ref.rsplit("/", 1)[-1]
    properties = schema["components"]["schemas"][model_name]["properties"]

    assert set(properties) >= {"success", "data", "message"}


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/boom", 404, "NOT_FOUND"),
        ("/conflict", 409, "CONFLICT"),
        ("/missing-route", 404, "NOT_FOUND"),
    ],
)
async def test_errors_use_the_error_envelope(
    contract_client: AsyncClient, path: str, status: int, code: str
) -> None:
    response = await contract_client.get(path)

    assert response.status_code == status
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == code
    assert isinstance(body["message"], str) and body["message"]


async def test_unhandled_errors_do_not_leak_internals(
    contract_app: FastAPI,
) -> None:
    """A bug must become a generic 500, never an internal detail on the wire."""
    transport = ASGITransport(app=contract_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text
    # The request id is still returned so the incident is traceable in the logs.
    assert body["meta"]["request_id"]


async def test_request_id_is_echoed_when_supplied(contract_client: AsyncClient) -> None:
    """An upstream correlation id is honoured so traces span the edge and API."""
    response = await contract_client.get("/plain", headers={"X-Request-ID": "edge-trace-123"})

    assert response.headers["X-Request-ID"] == "edge-trace-123"
    assert response.json()["meta"]["request_id"] == "edge-trace-123"


async def test_malicious_request_id_is_replaced(contract_client: AsyncClient) -> None:
    """A newline in a client-supplied id would allow log injection."""
    response = await contract_client.get("/plain", headers={"X-Request-ID": "abc\ndef INJECTED"})

    assert response.headers["X-Request-ID"] != "abc\ndef INJECTED"
