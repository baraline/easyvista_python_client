import httpx
import pytest

from easyvista_python_client._transport import BaseTransport
from easyvista_python_client.config import EasyvistaConfig
from easyvista_python_client.exceptions import (
    EasyvistaAuthError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaRateLimitError,
    EasyvistaServerError,
    EasyvistaValidationError,
)


def _base(token=True):
    if token:
        cfg = EasyvistaConfig(server="https://ev.test", account="acme", token="tok")
    else:
        cfg = EasyvistaConfig(
            server="https://ev.test", account="acme", login="u", password="p"
        )
    return BaseTransport(cfg)


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
