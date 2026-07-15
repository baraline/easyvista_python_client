import httpx
import pytest
import respx

from easyvista_python_client._transport import RequestSpec, SyncTransport
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
def test_send_get_returns_json_and_sends_auth_header():
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    with SyncTransport(_cfg()) as transport:
        result = transport.send(RequestSpec("GET", "requests"))
    assert result == {"records": []}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_send_post_sends_json_body():
    route = respx.post(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    with SyncTransport(_cfg()) as transport:
        transport.send(RequestSpec("POST", "requests", json={"requests": [{"a": 1}]}))
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {"requests": [{"a": 1}]}


@respx.mock
def test_send_retries_then_succeeds():
    route = respx.get(f"{ROOT}/requests").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    with SyncTransport(_cfg(max_retries=2)) as transport:
        result = transport.send(RequestSpec("GET", "requests"))
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_send_exhausts_retries_raises_server_error():
    respx.get(f"{ROOT}/requests").mock(return_value=httpx.Response(503))
    with SyncTransport(_cfg(max_retries=1)) as transport:
        with pytest.raises(EasyvistaServerError):
            transport.send(RequestSpec("GET", "requests"))


@respx.mock
def test_send_transport_error_raises_connection_error():
    respx.get(f"{ROOT}/requests").mock(side_effect=httpx.ConnectError("boom"))
    with SyncTransport(_cfg()) as transport:
        with pytest.raises(EasyvistaConnectionError):
            transport.send(RequestSpec("GET", "requests"))


@respx.mock
def test_send_does_not_retry_590_and_raises_validation_error():
    # A 590 (rejected create: missing mandatory field) is deterministic — it must
    # be raised immediately as a validation error, never retried, even when
    # max_retries > 0. The live body nests the real error as a JSON string.
    route = respx.post(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            590,
            json={"message": '{"error":"=(1,35) expected token","error_code":2013}'},
        )
    )
    with SyncTransport(_cfg(max_retries=2)) as transport:
        with pytest.raises(EasyvistaValidationError) as ei:
            transport.send(RequestSpec("POST", "requests", json={"requests": [{}]}))
    assert ei.value.status_code == 590
    assert ei.value.ev_code == "2013"
    assert route.call_count == 1
