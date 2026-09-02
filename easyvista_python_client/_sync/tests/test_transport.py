"""Transport tests, hand-written here and generated into the sync tree.

``unasync_build.py`` produces the twin of this module from it, so every name
here is spelled identically on both surfaces and every comment and docstring
is copied verbatim. Prose must therefore read true whichever tree the reader
has open -- never "the async twin of ...", and never a claim that holds on
only one surface.
"""

from collections.abc import Iterator

import httpx
import pytest
import respx

from easyvista_python_client._sync._transport import BaseTransport, Transport
from easyvista_python_client._transport import RequestSpec
from easyvista_python_client.config import DEFAULT_USER_AGENT, EasyvistaConfig
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


# --- BaseTransport: pure logic, no I/O ---------------------------------------
#
# BaseTransport carries no async or await, so these tests read identically in
# both trees. They still run twice, once per tree, because the generated
# BaseTransport is a distinct class from the hand-written one and nothing but
# the codegen makes the two agree.


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
    # The body is NOT interpolated into the message. Nothing redacts exception
    # text -- short tracebacks still emit the `E <Type>: <msg>` line and the `-r`
    # summary reuses it -- so an unrecognized body would print verbatim wherever
    # the exception surfaces, live instance content included (P2).
    message = str(info.value)
    assert "Internal Server Error" not in message
    assert "21-byte body" in message


def test_finish_with_non_ascii_error_body_counts_bytes_not_characters():
    """The byte count is genuinely bytes, not ``len(response.text)`` in disguise.

    "Internal Server Error" above is 21 characters *and* 21 UTF-8 bytes, so a
    regression back to ``len(response.text)`` would still print "21-byte body"
    there -- the two implementations are indistinguishable on an ASCII body.
    21 accented "e" characters are not: each one is 2 bytes in UTF-8, so the
    body is 42 bytes long while ``len(response.text)`` is 21. Verified below
    rather than assumed.
    """
    text = "é" * 21
    resp = httpx.Response(500, text=text)
    assert len(resp.text) == 21
    assert len(resp.content) == 42
    with pytest.raises(EasyvistaServerError) as info:
        _base().finish(resp)
    message = str(info.value)
    assert text not in message
    assert "42-byte body" in message
    assert "21-byte body" not in message


def test_finish_attaches_the_raw_body_to_the_exception_without_printing_it():
    """The body dropped from the message (P2) is not lost -- it moves to ``.body``.

    A PyPI consumer hitting a response this client does not recognize (an
    nginx HTML page, a WAF block page, a plain-text 503) has no other way to
    see what the server actually said, now that it is no longer interpolated
    into the message. Both halves matter together: ``.body`` without the
    message staying clean would re-open the P2 hole this exists to close, and
    a clean message without ``.body`` would make the bytes unrecoverable.
    """
    body = b"<html><body>502 Bad Gateway</body></html>"
    resp = httpx.Response(502, content=body)
    with pytest.raises(EasyvistaServerError) as info:
        _base().finish(resp)
    assert info.value.body == body
    assert "502 Bad Gateway" not in str(info.value)


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


def test_resolve_url_joins_a_relative_path_to_the_api_root():
    assert _base().resolve_url("requests/I1") == f"{ROOT}/requests/I1"


def test_resolve_url_passes_through_a_same_origin_absolute_url():
    url = "https://ev.test/download/attachment/42"
    assert _base().resolve_url(url) == url


def test_resolve_url_rejects_a_foreign_origin():
    # Load-bearing, not decoration: every request this transport makes carries
    # the instance's Bearer token, so following a URL a response body named
    # would hand that credential to whatever host it named.
    with pytest.raises(EasyvistaError, match="outside the configured instance"):
        _base().resolve_url("https://attacker.test/download/attachment/42")


def test_resolve_url_rejects_a_scheme_downgrade_on_the_same_host():
    with pytest.raises(EasyvistaError, match="outside the configured instance"):
        _base().resolve_url("http://ev.test/download/attachment/42")


def test_resolve_url_accepts_a_same_origin_url_with_different_host_casing():
    # DNS is case-insensitive and this API returns mixed-case URLs live.
    assert _base().resolve_url("https://EV.TEST/download/42") == (
        "https://EV.TEST/download/42"
    )


def test_resolve_url_still_rejects_a_userinfo_prefixed_foreign_host():
    # "attacker.test@ev.test" must not read as the host "ev.test" just
    # because case-folding was added.
    with pytest.raises(EasyvistaError, match="outside the configured instance"):
        _base().resolve_url("https://attacker.test@ev.test/download/42")


# --- Transport: the executor -------------------------------------------------


@respx.mock
def test_send_get_returns_json_and_sends_auth_header():
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    with Transport(_cfg()) as transport:
        result = transport.send(RequestSpec("GET", "requests"))
    assert result == {"records": []}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_send_post_sends_json_body():
    route = respx.post(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    with Transport(_cfg()) as transport:
        transport.send(
            RequestSpec("POST", "requests", json={"requests": [{"a": 1}]})
        )
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {"requests": [{"a": 1}]}


@respx.mock
def test_send_retries_then_succeeds():
    route = respx.get(f"{ROOT}/requests").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    with Transport(_cfg(max_retries=2)) as transport:
        result = transport.send(RequestSpec("GET", "requests"))
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_send_exhausts_retries_raises_server_error():
    respx.get(f"{ROOT}/requests").mock(return_value=httpx.Response(503))
    with Transport(_cfg(max_retries=1)) as transport:
        with pytest.raises(EasyvistaServerError):
            transport.send(RequestSpec("GET", "requests"))


@respx.mock
def test_send_transport_error_raises_connection_error():
    respx.get(f"{ROOT}/requests").mock(side_effect=httpx.ConnectError("boom"))
    with Transport(_cfg()) as transport:
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
    with Transport(_cfg(max_retries=2)) as transport:
        with pytest.raises(EasyvistaValidationError) as ei:
            transport.send(
                RequestSpec("POST", "requests", json={"requests": [{}]})
            )
    assert ei.value.status_code == 590
    assert ei.value.ev_code == "2013"
    assert route.call_count == 1


@respx.mock
def test_get_bytes_returns_raw_content_not_json():
    respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(200, content=b"\x00\x01\xff not json")
    )
    with Transport(_cfg()) as transport:
        got = transport.get_bytes("documents/1/content")
    assert got == b"\x00\x01\xff not json"


@respx.mock
def test_get_bytes_sends_the_bearer_header():
    route = respx.get("https://ev.test/download/42").mock(
        return_value=httpx.Response(200, content=b"ok")
    )
    with Transport(_cfg()) as transport:
        transport.get_bytes("https://ev.test/download/42")
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_get_bytes_maps_403_to_auth_error():
    respx.get(f"{ROOT}/documents/1/content").mock(return_value=httpx.Response(403))
    with Transport(_cfg()) as transport:
        with pytest.raises(EasyvistaAuthError):
            transport.get_bytes("documents/1/content")


@respx.mock
def test_get_bytes_retries_then_succeeds():
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=b"bytes")]
    )
    with Transport(_cfg(max_retries=2)) as transport:
        assert transport.get_bytes("documents/1/content") == b"bytes"
    assert route.call_count == 2


@respx.mock
def test_get_bytes_exhausts_retries_raises_server_error():
    respx.get(f"{ROOT}/documents/1/content").mock(return_value=httpx.Response(503))
    with Transport(_cfg(max_retries=1)) as transport:
        with pytest.raises(EasyvistaServerError):
            transport.get_bytes("documents/1/content")


@respx.mock
def test_get_bytes_transport_error_raises_connection_error():
    respx.get(f"{ROOT}/documents/1/content").mock(
        side_effect=httpx.ConnectError("boom")
    )
    with Transport(_cfg()) as transport:
        with pytest.raises(EasyvistaConnectionError):
            transport.get_bytes("documents/1/content")


def test_get_bytes_rejects_a_foreign_origin():
    # Guards the wiring, not just the helper: _do_get_bytes must route through
    # resolve_url. Without this, dropping that call breaks nothing in the suite.
    with Transport(_cfg()) as transport:
        with pytest.raises(EasyvistaError, match="outside the configured instance"):
            transport.get_bytes("https://attacker.test/download/42")


@respx.mock
def test_get_bytes_drops_the_bearer_token_on_a_cross_host_redirect():
    # resolve_url only vets the FIRST hop; `follow_redirects=True` means the
    # instance can still bounce us somewhere else. What keeps the token from
    # following is httpx stripping Authorization when a redirect leaves the
    # origin -- third-party behaviour the docstring on get_bytes relies on, and
    # `httpx>=0.27` leaves unbounded, so pin it here rather than trust it. This
    # module is generated into the other tree, so the pin lands on both httpx
    # clients -- separate implementations upstream, each needing its own.
    respx.get("https://ev.test/download/42").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://cdn.attacker.test/blob/42"}
        )
    )
    foreign = respx.get("https://cdn.attacker.test/blob/42").mock(
        return_value=httpx.Response(200, content=b"blob")
    )
    with Transport(_cfg()) as transport:
        content = transport.get_bytes("https://ev.test/download/42")
    assert content == b"blob"
    leaked = "authorization" in foreign.calls.last.request.headers
    assert not leaked, "the instance token followed a redirect off the instance"


@respx.mock
def test_get_bytes_keeps_the_bearer_token_on_a_same_host_redirect():
    # Control for the test above: without it, a transport that simply never
    # sent Authorization at all would look like a pass. A download URL commonly
    # redirects to a signed location on the same host, and that hop must stay
    # authenticated.
    respx.get("https://ev.test/download/42").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://ev.test/download/42/signed"}
        )
    )
    signed = respx.get("https://ev.test/download/42/signed").mock(
        return_value=httpx.Response(200, content=b"blob")
    )
    with Transport(_cfg()) as transport:
        content = transport.get_bytes("https://ev.test/download/42")
    assert content == b"blob"
    assert signed.calls.last.request.headers["Authorization"] == "Bearer tok"


# --- stream_bytes ------------------------------------------------------------
#
# The streaming download. Its contract is "identical to get_bytes except that
# the body arrives in pieces", so most of these are the get_bytes assertions
# above re-made against the chunked path -- that duplication is the point, since
# the two implementations share no code past `resolve_url`. The one claim with
# no get_bytes counterpart is the retry boundary: retrying stops once a byte has
# reached the caller, because restarting would deliver it twice.


class _StreamThatFailsMidBody(httpx.SyncByteStream):
    """A response body that delivers ``prefix`` and then drops the connection.

    ``respx`` can fail a request before a response exists, which is what the
    ``side_effect=httpx.ConnectError`` mocks elsewhere in this module do. It has
    no way to fail one *after* the status line, and that is exactly the case the
    retry boundary is about -- so the failure is injected into the body stream
    itself, which httpx surfaces as a real ``TransportError`` while iterating.
    """

    def __init__(self, prefix: bytes) -> None:
        self._prefix = prefix

    def __iter__(self) -> Iterator[bytes]:
        yield self._prefix
        raise httpx.ReadError("connection dropped mid-body")


class _StreamThatFailsBeforeTheFirstByte(httpx.SyncByteStream):
    """A response body that drops the connection without yielding anything.

    The sibling of :class:`_StreamThatFailsMidBody`, for the *other* side of the
    retry boundary: the status line arrived, so this is past the point respx can
    fail a request, but no byte has reached the caller yet, so restarting is
    still safe and must happen.
    """

    def __iter__(self) -> Iterator[bytes]:
        raise httpx.ReadError("dropped before the first byte")
        yield b""  # unreachable; the yield is what makes this a generator function


def _collect(chunks: Iterator[bytes]) -> list[bytes]:
    """Every chunk a stream yields, kept separate rather than joined."""
    return [chunk for chunk in chunks]


@respx.mock
def test_stream_bytes_reassembles_to_the_whole_body():
    # 10244 bytes at chunk_size=1024: deliberately NOT a multiple of it, so the
    # last chunk is a short one. A body sized to an exact multiple never
    # exercises the ragged tail, and the reassembly assertion below would
    # pass either way.
    body = bytes(range(256)) * 40 + b"tail"
    respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(200, content=body)
    )
    with Transport(_cfg()) as transport:
        chunks = _collect(
            transport.stream_bytes("documents/1/content", chunk_size=1024)
        )
    assert b"".join(chunks) == body
    # More than one chunk, and each bounded: proves the body is delivered
    # progressively rather than read whole and handed over in a single piece.
    assert len(chunks) == 11
    assert max(len(chunk) for chunk in chunks) <= 1024
    assert len(chunks[-1]) == 4, "the short final chunk was padded or dropped"


@respx.mock
def test_stream_bytes_chunks_at_the_documented_default_size():
    """The default chunk size is 64 KiB, and this is what says so.

    ``DEFAULT_STREAM_CHUNK_SIZE`` is quoted as "64 KiB" in the CHANGELOG, in the
    document-workflow skill and in the constant's own comment (whose "a 32 MB
    attachment is ~512 iterations" arithmetic only holds at that value). Every
    other chunk-counting test passes ``chunk_size`` explicitly, so without this
    one the constant could change to anything and leave all three false with a
    green suite. 160 KiB of body -> three chunks, the last a short one.
    """
    body = bytes(range(256)) * 640  # 163840 bytes == 2.5 * 64 KiB
    respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(200, content=body)
    )
    with Transport(_cfg()) as transport:
        chunks = _collect(transport.stream_bytes("documents/1/content"))
    assert b"".join(chunks) == body
    assert [len(chunk) for chunk in chunks] == [65536, 65536, 32768]


@pytest.mark.parametrize("bad", [0, -8])
def test_stream_bytes_refuses_a_non_positive_chunk_size(bad):
    """The newest public parameter must fail as bad input, not as a library bug.

    Left unguarded, httpx raises from inside its own ``ByteChunker`` several
    frames below this client: ``chunk_size=0`` surfaces as "range() arg 3 must
    not be zero" and a negative one as "list index out of range". A caller
    computing a chunk size reads either as our bug. No request is made, so this
    needs no mock -- and because ``stream_bytes`` is a generator, the raise lands
    on the first iteration step, matching the deferred ``ValueError`` for a
    record with no download URL.
    """
    with Transport(_cfg()) as transport:
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            _collect(
                transport.stream_bytes("documents/1/content", chunk_size=bad)
            )


@respx.mock
def test_stream_bytes_yields_nothing_for_an_empty_body():
    respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(200, content=b"")
    )
    with Transport(_cfg()) as transport:
        assert _collect(transport.stream_bytes("documents/1/content")) == []


@respx.mock
def test_stream_bytes_sends_the_bearer_header():
    route = respx.get("https://ev.test/download/42").mock(
        return_value=httpx.Response(200, content=b"ok")
    )
    with Transport(_cfg()) as transport:
        _collect(transport.stream_bytes("https://ev.test/download/42"))
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_stream_bytes_maps_403_to_auth_error():
    # The status is on an unread streaming response, whose `.content` raises
    # until the body is read -- so the error mapping cannot simply be reused, it
    # has to read the body first. This asserts the mapped type AND that the
    # parsed EasyVista fields survived that detour.
    respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(403, json={"error": "forbidden", "code": "9"})
    )
    with Transport(_cfg()) as transport:
        with pytest.raises(EasyvistaAuthError) as ei:
            _collect(transport.stream_bytes("documents/1/content"))
    assert ei.value.status_code == 403
    assert ei.value.ev_message == "forbidden"
    assert ei.value.ev_code == "9"


@respx.mock
def test_stream_bytes_does_not_retry_a_590():
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(590, json={"error": "rejected"})
    )
    with Transport(_cfg(max_retries=3)) as transport:
        with pytest.raises(EasyvistaValidationError):
            _collect(transport.stream_bytes("documents/1/content"))
    assert route.call_count == 1


@respx.mock
def test_stream_bytes_retries_a_retryable_status_on_the_open():
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=b"bytes")]
    )
    with Transport(_cfg(max_retries=2)) as transport:
        chunks = _collect(transport.stream_bytes("documents/1/content"))
    assert b"".join(chunks) == b"bytes"
    assert route.call_count == 2


@respx.mock
def test_stream_bytes_exhausts_retries_raises_server_error():
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(503)
    )
    with Transport(_cfg(max_retries=1)) as transport:
        with pytest.raises(EasyvistaServerError):
            _collect(transport.stream_bytes("documents/1/content"))
    assert route.call_count == 2


@respx.mock
def test_stream_bytes_transport_error_on_the_open_raises_connection_error():
    respx.get(f"{ROOT}/documents/1/content").mock(
        side_effect=httpx.ConnectError("boom")
    )
    with Transport(_cfg()) as transport:
        with pytest.raises(EasyvistaConnectionError):
            _collect(transport.stream_bytes("documents/1/content"))


@respx.mock
def test_stream_bytes_retries_a_failure_fetching_the_first_chunk():
    """The first chunk is fetched INSIDE the retried unit. This is what pins it.

    ``_open_stream`` takes the first chunk itself, so a body that dies before
    yielding a byte is still a safe restart -- nothing has reached the caller, so
    replaying the request cannot deliver anything twice. Move that fetch out of
    the retried unit (open there, iterate the whole body here) and the failure
    below escapes as ``EasyvistaConnectionError`` on the first attempt instead,
    with ``call_count == 1``. Every other ``stream_bytes`` test passes under both
    arrangements, including the mid-body one just after this: the two differ only
    on a first-chunk failure, which is only this test.
    """
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        side_effect=[
            httpx.Response(200, stream=_StreamThatFailsBeforeTheFirstByte()),
            httpx.Response(200, content=b"0123456789abcdef"),
        ]
    )
    with Transport(_cfg(max_retries=2)) as transport:
        chunks = _collect(
            transport.stream_bytes("documents/1/content", chunk_size=8)
        )
    assert b"".join(chunks) == b"0123456789abcdef"
    assert route.call_count == 2, "a pre-first-byte failure was not retried"


@respx.mock
def test_stream_bytes_does_not_retry_after_a_chunk_has_been_yielded():
    """A mid-body failure is the caller's to handle, never silently restarted.

    Retrying here would hand the caller the opening bytes a second time, so the
    request is committed the moment a chunk is delivered. The delivered prefix
    stays visible -- the caller keeps what it already collected -- and the
    failure arrives as a mapped ``EasyvistaConnectionError``, not as a raw httpx
    error. A "helpful" change making this resumable fails on the call count.
    """
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(
            200, stream=_StreamThatFailsMidBody(b"0123456789abcdef")
        )
    )
    collected: list[bytes] = []
    with Transport(_cfg(max_retries=3)) as transport:
        with pytest.raises(EasyvistaConnectionError):
            for chunk in transport.stream_bytes(
                "documents/1/content", chunk_size=8
            ):
                collected.append(chunk)
    assert b"".join(collected) == b"0123456789abcdef"
    assert route.call_count == 1, "a mid-stream failure was retried"


def test_stream_bytes_rejects_a_foreign_origin():
    # The same-origin guard is a security property of the download path, not of
    # one method on it: every request carries the instance Bearer token. Nothing
    # is requested until iteration starts, so the refusal surfaces there.
    with Transport(_cfg()) as transport:
        with pytest.raises(EasyvistaError, match="outside the configured instance"):
            _collect(transport.stream_bytes("https://attacker.test/download/42"))


@respx.mock
def test_stream_bytes_drops_the_bearer_token_on_a_cross_host_redirect():
    # `follow_redirects=True` is as deliberate here as on get_bytes (a download
    # URL commonly redirects to a signed location), and so is the reason it is
    # safe: httpx strips Authorization when a redirect leaves the origin. Pinned
    # on this path too, because the streaming send() call passes the flag itself
    # rather than inheriting anything from the non-streaming one.
    respx.get("https://ev.test/download/42").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://cdn.attacker.test/blob/42"}
        )
    )
    foreign = respx.get("https://cdn.attacker.test/blob/42").mock(
        return_value=httpx.Response(200, content=b"blob")
    )
    with Transport(_cfg()) as transport:
        chunks = _collect(transport.stream_bytes("https://ev.test/download/42"))
    assert b"".join(chunks) == b"blob"
    leaked = "authorization" in foreign.calls.last.request.headers
    assert not leaked, "the instance token followed a redirect off the instance"


@respx.mock
def test_stream_bytes_keeps_the_bearer_token_on_a_same_host_redirect():
    # Control for the test above, exactly as on get_bytes: without it, a path
    # that never sent Authorization at all would look like a pass.
    respx.get("https://ev.test/download/42").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://ev.test/download/42/signed"}
        )
    )
    signed = respx.get("https://ev.test/download/42/signed").mock(
        return_value=httpx.Response(200, content=b"blob")
    )
    with Transport(_cfg()) as transport:
        chunks = _collect(transport.stream_bytes("https://ev.test/download/42"))
    assert b"".join(chunks) == b"blob"
    assert signed.calls.last.request.headers["Authorization"] == "Bearer tok"


# --- per-deployment adaptation: headers, params, download hosts ---------------


def test_headers_carry_the_package_user_agent_by_default():
    assert _base().headers()["User-Agent"] == DEFAULT_USER_AGENT


def test_user_agent_config_replaces_the_default():
    assert BaseTransport(_cfg(user_agent="my-app/1.4")).headers()["User-Agent"] == (
        "my-app/1.4"
    )


def test_extra_headers_override_every_default_but_not_the_credential():
    # extra_headers is merged LAST, so it wins over Accept, Content-Type and the
    # User-Agent alike. It cannot reach the credential: EasyvistaConfig refuses
    # an Authorization key at construction, so by the time headers() runs there
    # is nothing left to guard against.
    transport = BaseTransport(
        _cfg(
            extra_headers={
                "Accept": "text/csv",
                "Content-Type": "text/csv",
                "User-Agent": "override/9",
                "Ocp-Apim-Subscription-Key": "gateway-key",
            }
        )
    )
    headers = transport.headers()
    assert headers["Accept"] == "text/csv"
    assert headers["Content-Type"] == "text/csv"
    assert headers["User-Agent"] == "override/9"
    assert headers["Ocp-Apim-Subscription-Key"] == "gateway-key"
    assert headers["Authorization"] == "Bearer tok"


def test_merge_params_layers_config_then_call_then_spec():
    # All three empty returns None, so a request that took no parameters before
    # still takes none -- that is what keeps today's wire unchanged.
    assert BaseTransport(_cfg()).merge_params(None, None) is None
    transport = BaseTransport(_cfg(default_params={"formatDate": "iso", "shared": "c"}))
    assert transport.merge_params(None, None) == {"formatDate": "iso", "shared": "c"}
    # The caller beats config, and the spec beats both: the spec is what sets
    # search/max_rows/offset, so a caller must not be able to replace them.
    assert transport.merge_params({"shared": "call"}, None)["shared"] == "call"
    assert transport.merge_params({"shared": "call"}, {"shared": "spec"})["shared"] == (
        "spec"
    )


def test_download_headers_carry_no_credential_and_no_extra_headers():
    # The whole point of allowing a foreign download host is that reaching it
    # must not hand that host this instance's token -- nor a second secret
    # sitting in extra_headers.
    bearer = EasyvistaConfig(
        server="https://ev.test",
        account="acme",
        token="tok",
        extra_headers={"X-Api-Key": "SECRET"},
    )
    basic = EasyvistaConfig(
        server="https://ev.test",
        account="acme",
        login="u",
        password="p",
        extra_headers={"X-Api-Key": "SECRET"},
    )
    for cfg in (bearer, basic):
        assert BaseTransport(cfg).download_headers() == {
            "User-Agent": DEFAULT_USER_AGENT
        }


def _allowing(*hosts):
    return BaseTransport(_cfg(additional_download_hosts=set(hosts)))


def test_resolve_url_admits_an_allow_listed_https_host():
    url = "https://cdn.allowed.test/blob/1"
    assert _allowing("cdn.allowed.test").resolve_url(url) == url


def test_resolve_url_allow_list_is_https_only():
    # Opting a host in must never be usable to downgrade a fetch to cleartext.
    with pytest.raises(EasyvistaError):
        _allowing("cdn.allowed.test").resolve_url("http://cdn.allowed.test/blob/1")


def test_resolve_url_still_rejects_a_host_that_is_not_listed():
    with pytest.raises(EasyvistaError, match="additional_download_hosts"):
        _allowing("cdn.allowed.test").resolve_url("https://attacker.test/blob/1")


def test_resolve_url_allow_list_still_rejects_a_userinfo_prefix():
    # The raw-netloc comparison carries over to the new branch, so
    # "attacker.test@cdn.allowed.test" matches no allow-listed host.
    with pytest.raises(EasyvistaError):
        _allowing("cdn.allowed.test").resolve_url(
            "https://attacker.test@cdn.allowed.test/blob/1"
        )


def test_is_offsite_answers_false_for_the_instance_even_when_listed():
    # A caller who redundantly lists their own instance host must not thereby
    # strip their own credential from every download.
    transport = _allowing("ev.test", "cdn.allowed.test")
    assert transport.is_offsite(f"{ROOT}/documents/1/content") is False
    assert transport.is_offsite("https://cdn.allowed.test/blob/1") is True


@respx.mock
def test_get_bytes_sends_no_credential_to_an_allow_listed_host():
    # THE LOAD-BEARING TEST. The token is attached to the instance client at
    # CLIENT level -- as a header for Bearer, as an httpx.Auth for Basic -- and
    # httpx can remove neither per request. A second, credential-free client is
    # what makes this assertion hold, so both auth mechanisms are checked here:
    # one does not cover the other.
    bearer = EasyvistaConfig(
        server="https://ev.test",
        account="acme",
        token="tok",
        additional_download_hosts={"cdn.allowed.test"},
    )
    basic = EasyvistaConfig(
        server="https://ev.test",
        account="acme",
        login="u",
        password="p",
        additional_download_hosts={"cdn.allowed.test"},
    )
    for cfg in (bearer, basic):
        route = respx.get("https://cdn.allowed.test/blob/1").mock(
            return_value=httpx.Response(200, content=b"payload")
        )
        with Transport(cfg) as transport:
            fetched = transport.get_bytes("https://cdn.allowed.test/blob/1")
        assert fetched == b"payload"
        assert "authorization" not in route.calls.last.request.headers


@respx.mock
def test_get_bytes_still_authenticates_against_the_instance():
    # The other half of the pair: opting a foreign host in must not disturb the
    # instance's own downloads.
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(200, content=b"payload")
    )
    with Transport(_cfg(additional_download_hosts={"cdn.allowed.test"})) as t:
        assert t.get_bytes("documents/1/content") == b"payload"
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_stream_bytes_sends_no_credential_to_an_allow_listed_host():
    # _open_stream selects its client separately and shares no code with
    # _do_get_bytes past resolve_url, so the guarantee is asserted twice.
    route = respx.get("https://cdn.allowed.test/blob/1").mock(
        return_value=httpx.Response(200, content=b"payload")
    )
    with Transport(_cfg(additional_download_hosts={"cdn.allowed.test"})) as t:
        chunks = _collect(t.stream_bytes("https://cdn.allowed.test/blob/1"))
    assert b"".join(chunks) == b"payload"
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
def test_stream_bytes_still_authenticates_against_the_instance():
    route = respx.get(f"{ROOT}/documents/1/content").mock(
        return_value=httpx.Response(200, content=b"payload")
    )
    with Transport(_cfg(additional_download_hosts={"cdn.allowed.test"})) as t:
        chunks = _collect(t.stream_bytes("documents/1/content"))
    assert b"".join(chunks) == b"payload"
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


def test_the_download_client_exists_only_when_opted_in_and_is_closed():
    plain = Transport(_cfg())
    assert plain._download_client is None
    plain.close()

    opted = Transport(_cfg(additional_download_hosts={"cdn.allowed.test"}))
    assert opted._download_client is not None
    opted.close()
    assert opted._client.is_closed
    assert opted._download_client.is_closed


@respx.mock
def test_send_layers_the_three_parameter_sources_on_the_wire():
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    cfg = _cfg(default_params={"max_rows": 1, "formatDate": "config"})
    with Transport(cfg) as transport:
        transport.send(
            RequestSpec("GET", "requests", params={"max_rows": 10}),
            params={"max_rows": 5, "formatDate": "iso"},
        )
    url = route.calls.last.request.url
    assert url.params["max_rows"] == "10"  # the spec wins
    assert url.params["formatDate"] == "iso"  # the call beats config


@respx.mock
def test_request_spec_headers_override_the_client_level_ones():
    route = respx.post(f"{ROOT}/upload").mock(return_value=httpx.Response(200, json={}))
    with Transport(_cfg()) as transport:
        transport.send(
            RequestSpec("POST", "upload", headers={"Content-Type": "text/csv"})
        )
    assert route.calls.last.request.headers["Content-Type"] == "text/csv"


def test_request_spec_refuses_the_credential_in_its_headers():
    with pytest.raises(ValueError, match="must not set"):
        RequestSpec("GET", "requests", headers={"authorization": "Bearer other"})
