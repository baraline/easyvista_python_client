import httpx
import pytest
import respx

from easyvista_python_client._transport import (
    AsyncTransport,
    BaseTransport,
    RequestSpec,
    SyncTransport,
)
from easyvista_python_client.config import EasyvistaConfig
from easyvista_python_client.exceptions import (
    EasyvistaAuthError,
    EasyvistaConnectionError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaRateLimitError,
    EasyvistaServerError,
    EasyvistaValidationError,
)

ROOT = "https://ev.test/api/v1/acme"


def _base(token=True):
    if token:
        cfg = EasyvistaConfig(server="https://ev.test", account="acme", token="tok")
    else:
        cfg = EasyvistaConfig(
            server="https://ev.test", account="acme", login="u", password="p"
        )
    return BaseTransport(cfg)


def _cfg(**kw):
    return EasyvistaConfig(server="https://ev.test", account="acme", token="tok", **kw)


def test_build_url_joins_api_root_and_path():
    assert _base().build_url("requests") == "https://ev.test/api/v1/acme/requests"
    assert (
        _base().build_url("requests/123") == "https://ev.test/api/v1/acme/requests/123"
    )


def test_bearer_headers_set_authorization():
    headers = _base().headers()
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Accept"] == "application/json"


def test_basic_auth_returns_httpx_auth_and_no_bearer_header():
    base = _base(token=False)
    assert "Authorization" not in base.headers()
    assert isinstance(base.auth(), httpx.BasicAuth)


def test_finish_returns_json_on_success():
    resp = httpx.Response(200, json={"ok": True})
    assert _base().finish(resp) == {"ok": True}


def test_finish_returns_empty_dict_on_empty_body():
    resp = httpx.Response(204)
    assert _base().finish(resp) == {}


@pytest.mark.parametrize(
    "status,exc",
    [
        (401, EasyvistaAuthError),
        (403, EasyvistaAuthError),
        (404, EasyvistaNotFound),
        (400, EasyvistaValidationError),
        (429, EasyvistaRateLimitError),
        (500, EasyvistaServerError),
        (418, EasyvistaError),
    ],
)
def test_finish_raises_mapped_errors(status, exc):
    # EasyVista's real error shape: the code is under "error_code", the human
    # message is under "error" (see _extract_error).
    resp = httpx.Response(status, json={"error_code": "ECODE", "error": "nope"})
    with pytest.raises(exc) as info:
        _base().finish(resp)
    assert info.value.status_code == status
    assert info.value.ev_code == "ECODE"
    assert info.value.ev_message == "nope"


def test_finish_with_non_json_error_body():
    resp = httpx.Response(500, text="Internal Server Error")
    with pytest.raises(EasyvistaServerError) as info:
        _base().finish(resp)
    assert info.value.status_code == 500
    assert info.value.ev_code is None
    assert info.value.ev_message is None


def test_is_retryable_status():
    base = _base()
    assert base.is_retryable_status(503) is True
    assert base.is_retryable_status(429) is True
    assert base.is_retryable_status(404) is False


def test_extract_error_reads_error_code_shape():
    resp = httpx.Response(
        590, json={"error": "=(1,35) expected token", "error_code": 2013}
    )
    code, message = _base()._extract_error(resp)
    assert code == "2013"
    assert message == "=(1,35) expected token"


def test_extract_error_unwraps_nested_json_message():
    # The live 590 body nests the real error as a JSON *string* under "message".
    resp = httpx.Response(
        590,
        json={"message": '{"error":"=(1,35) expected token","error_code":2013}'},
    )
    code, message = _base()._extract_error(resp)
    assert code == "2013"
    assert message == "=(1,35) expected token"


def test_extract_error_ignores_malformed_nested_message():
    # A "message" that starts with "{" but is not valid JSON is left untouched.
    resp = httpx.Response(590, json={"message": "{not valid json"})
    code, message = _base()._extract_error(resp)
    assert code is None
    assert message == "{not valid json"


def test_extract_error_non_dict_json_returns_none():
    # A JSON body that is not an object yields no code/message.
    resp = httpx.Response(500, json=["unexpected", "list"])
    assert _base()._extract_error(resp) == (None, None)


def test_590_maps_to_validation_error_with_code():
    resp = httpx.Response(
        590, json={"error": "Invalid catalog reference", "error_code": 2013}
    )
    with pytest.raises(EasyvistaValidationError) as ei:
        _base()._raise_for_response(resp)
    assert ei.value.status_code == 590
    assert ei.value.ev_code == "2013"


def test_590_is_not_retryable_but_other_5xx_are():
    base = _base()
    assert base.is_retryable_status(500) is True
    assert base.is_retryable_status(503) is True
    assert base.is_retryable_status(590) is False
    assert base.is_retryable_status(429) is True


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
