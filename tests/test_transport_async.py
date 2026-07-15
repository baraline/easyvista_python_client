import httpx
import pytest
import respx

from easyvista_python_client._transport import AsyncTransport, RequestSpec
from easyvista_python_client.config import EasyvistaConfig
from easyvista_python_client.exceptions import (
    EasyvistaConnectionError,
    EasyvistaServerError,
    EasyvistaValidationError,
)

ROOT = "https://ev.test/api/v1/acme"


def _cfg(**kw):
    return EasyvistaConfig(server="https://ev.test", account="acme", token="tok", **kw)


@respx.mock
async def test_asend_returns_json_and_sends_auth_header():
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncTransport(_cfg()) as transport:
        result = await transport.asend(RequestSpec("GET", "requests"))
    assert result == {"records": []}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
async def test_asend_retries_then_succeeds():
    route = respx.get(f"{ROOT}/requests").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    async with AsyncTransport(_cfg(max_retries=2)) as transport:
        result = await transport.asend(RequestSpec("GET", "requests"))
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_asend_exhausts_retries_raises_server_error():
    respx.get(f"{ROOT}/requests").mock(return_value=httpx.Response(503))
    async with AsyncTransport(_cfg(max_retries=1)) as transport:
        with pytest.raises(EasyvistaServerError):
            await transport.asend(RequestSpec("GET", "requests"))


@respx.mock
async def test_asend_transport_error_raises_connection_error():
    respx.get(f"{ROOT}/requests").mock(side_effect=httpx.ConnectError("boom"))
    async with AsyncTransport(_cfg()) as transport:
        with pytest.raises(EasyvistaConnectionError):
            await transport.asend(RequestSpec("GET", "requests"))


@respx.mock
async def test_asend_does_not_retry_590_and_raises_validation_error():
    # Async parity for the deterministic-590 fix: raised once as a validation
    # error, never retried, even with max_retries > 0.
    route = respx.post(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            590,
            json={"message": '{"error":"=(1,35) expected token","error_code":2013}'},
        )
    )
    async with AsyncTransport(_cfg(max_retries=2)) as transport:
        with pytest.raises(EasyvistaValidationError) as ei:
            await transport.asend(
                RequestSpec("POST", "requests", json={"requests": [{}]})
            )
    assert ei.value.status_code == 590
    assert ei.value.ev_code == "2013"
    assert route.call_count == 1
