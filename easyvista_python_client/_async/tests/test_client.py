"""Client tests, hand-written here and generated into the sync tree.

``unasync_build.py`` produces the twin of this module from it, so every test
name is spelled identically on both surfaces and every comment and docstring
is copied verbatim. Prose must therefore read true whichever tree the reader
has open -- never "the twin of ...", and never a claim that holds on only one
surface.

Claims that *are* about one surface only live in ``test_concurrency.py``,
which is hand-written on both sides and never generated.
"""

import dataclasses
import json
from collections.abc import AsyncIterator

import httpx
import pydantic
import pytest
import respx

from easyvista_python_client._async import client as client_module
from easyvista_python_client._async.client import AsyncEasyvistaClient
from easyvista_python_client.config import EasyvistaConfig
from easyvista_python_client.directory import DepartmentContext
from easyvista_python_client.exceptions import (
    EasyvistaAuthError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaServerError,
    EasyvistaValidationError,
)
from easyvista_python_client.models.action import ActionUpdate, PostAction
from easyvista_python_client.models.asset import PostAsset
from easyvista_python_client.models.department import (
    Department,
    DepartmentUpdate,
    PostDepartment,
)
from easyvista_python_client.models.document import Document
from easyvista_python_client.models.employee import (
    Employee,
    EmployeeUpdate,
    PostEmployee,
)
from easyvista_python_client.models.request import PostRequest, RequestUpdate

ROOT = "https://ev.test/api/v1/acme"


# --- tickets -----------------------------------------------------------------


@respx.mock
async def test_create_and_get_ticket(config):
    respx.post(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": [{"RFC_NUMBER": "I1"}]})
    )
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1", "STATUS_ID": 2})
    )
    async with AsyncEasyvistaClient(config) as client:
        created = await client.create_ticket(PostRequest(catalog_code="C"))
        fetched = await client.get_ticket("I1")
    assert created.rfc_number == "I1"
    assert fetched.status_id == 2


@respx.mock
async def test_create_tickets_creates_each_ticket(config):
    # EasyVista's POST /requests creates only the first item of a multi-item
    # body, so create_tickets must fan out to one POST per ticket.
    route = respx.post(f"{ROOT}/requests").mock(
        side_effect=[
            httpx.Response(200, json={"HREF": f"{ROOT}/requests/I1"}),
            httpx.Response(200, json={"HREF": f"{ROOT}/requests/I2"}),
        ]
    )
    async with AsyncEasyvistaClient(config) as client:
        created = await client.create_tickets(
            [PostRequest(catalog_code="A"), PostRequest(catalog_code="B")]
        )
    assert route.call_count == 2
    assert [t.rfc_number for t in created] == ["I1", "I2"]


@respx.mock
async def test_search_tickets(config):
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"RFC_NUMBER": "I1"}],
                "record_count": 1,
                "total_record_count": 3,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        result = await client.search_tickets(search='STATUS_ID:"3"', max_rows=10)
    assert result.total_record_count == 3
    assert result.records[0].rfc_number == "I1"


@respx.mock
async def test_search_tickets_applies_default_max_rows(config):
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.search_tickets()
    assert route.calls.last.request.url.params["max_rows"] == "100"


@respx.mock
async def test_update_and_close_ticket(config):
    respx.put(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"records": [{"RFC_NUMBER": "I1"}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.update_ticket("I1", RequestUpdate(impact_id=4))
        await client.close_ticket("I1", comment="resolved")


@respx.mock
async def test_update_ticket_sends_title(config):
    route = respx.put(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(
            200, json={"RFC_NUMBER": "I1", "TITLE": "New title"}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        updated = await client.update_ticket("I1", RequestUpdate(title="New title"))
    assert json.loads(route.calls.last.request.content) == {"title": "New title"}
    assert updated.title == "New title"


@respx.mock
async def test_create_and_list_actions(config):
    respx.post(f"{ROOT}/requests/I1/actions").mock(
        return_value=httpx.Response(200, json={"records": [{"ACTION_ID": 5}]})
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"records": [{"ACTION_ID": 5}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        action = await client.create_action(
            "I1", PostAction(action_type_id=94, group_id=3, description="hi")
        )
        listed = await client.list_actions("I1")
    assert action.action_id == 5
    assert listed[0].action_id == 5


@respx.mock
async def test_list_actions_forwards_a_fields_projection(config):
    """The client must pass fields= through, not just accept it.

    EV-R3: fields= is what turns comment metadata into one request per ticket
    instead of one request per action.
    """
    route = respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.list_actions("I240101_0001", fields=["ACTION_ID", "LAST_UPDATE"])
    assert route.calls.last.request.url.params["fields"] == "ACTION_ID,LAST_UPDATE"


@respx.mock
async def test_list_actions_sends_the_configured_row_cap(config):
    """``list_actions`` returns one page, so the cap must be the client's own.

    Without this the request carried no ``max_rows`` at all and the truncation
    point was the server's unstated default -- invisible to the caller and not
    raisable by configuration.
    """
    route = respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        expected = str(client.config.default_max_rows)
        await client.list_actions("I240101_0001")
    assert route.calls.last.request.url.params["max_rows"] == expected


@respx.mock
async def test_get_action_fetches_the_item_level_record(config):
    respx.get(f"{ROOT}/actions/52990").mock(
        return_value=httpx.Response(
            200,
            json={
                "ACTION_ID": 52990,
                "DESCRIPTION": {"HREF": f"{ROOT}/actions/52990/description"},
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        action = await client.get_action(52990)
    assert action.action_id == 52990
    assert action.description == {"HREF": f"{ROOT}/actions/52990/description"}


@respx.mock
async def test_update_action_sends_a_put_to_the_top_level_path(config):
    """The nested requests/{rfc}/actions/{id} form returns 403 (verified live)."""
    route = respx.put(f"{ROOT}/actions/57483").mock(
        return_value=httpx.Response(200, json={"ACTION_ID": 57483})
    )
    async with AsyncEasyvistaClient(config) as client:
        action = await client.update_action(57483, ActionUpdate(description="edited"))
    assert json.loads(route.calls.last.request.content) == {"description": "edited"}
    assert action.action_id == 57483


@respx.mock
async def test_from_env_constructs_working_client(monkeypatch):
    monkeypatch.setenv("EASYVISTA_URL", "https://ev.test")
    monkeypatch.setenv("EASYVISTA_ACCOUNT", "acme")
    monkeypatch.setenv("EASYVISTA_TOKEN", "tok")
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    async with AsyncEasyvistaClient.from_env() as client:
        ticket = await client.get_ticket("I1")
    assert ticket.rfc_number == "I1"


@respx.mock
async def test_count_tickets_returns_total_record_count(config):
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"RFC_NUMBER": "I1"}],
                "record_count": 1,
                "total_record_count": 42,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        total = await client.count_tickets(search='STATUS_ID:"3"')
    assert total == 42  # the full match count, not the page's record_count
    assert route.call_count == 1
    assert route.calls.last.request.url.params["max_rows"] == "1"
    assert route.calls.last.request.url.params["search"] == 'STATUS_ID:"3"'


# --- assets and documents ----------------------------------------------------


@respx.mock
async def test_create_and_get_asset(config):
    respx.post(f"{ROOT}/assets").mock(
        return_value=httpx.Response(201, json={"HREF": f"{ROOT}/assets/9504"})
    )
    respx.get(f"{ROOT}/assets/9504").mock(
        return_value=httpx.Response(200, json={"ASSET_TAG": "T1"})
    )
    async with AsyncEasyvistaClient(config) as client:
        created = await client.create_asset(PostAsset(catalog_id=3153, asset_tag="T1"))
        fetched = await client.get_asset("9504")
    assert created.href.endswith("/assets/9504")
    assert fetched.asset_tag == "T1"


@respx.mock
async def test_search_assets(config):
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"ASSET_TAG": "T1"}],
                "record_count": 1,
                "total_record_count": 2,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        result = await client.search_assets(search="ASSET_TAG~T")
    assert result.total_record_count == 2
    assert result.records[0].asset_tag == "T1"


@respx.mock
async def test_search_assets_applies_default_max_rows(config):
    route = respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.search_assets()
    assert route.calls.last.request.url.params["max_rows"] == "100"


@respx.mock
async def test_add_and_list_documents(config):
    add_route = respx.post(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(201, json={"HREF": f"{ROOT}/requests/I1"})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"records": [{"HREF": "u1"}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        doc = await client.add_document("I1", filename="a.txt", content=b"hi")
        listed = await client.list_documents("I1")
    assert doc.href.endswith("/requests/I1")
    assert listed[0].href == "u1"
    body = json.loads(add_route.calls.last.request.content)
    assert body["documents"][0]["filename"] == "a.txt"


@respx.mock
async def test_delete_document_sends_a_delete_to_the_nested_path(config):
    """Returns None: the API answers a delete with an empty body."""
    route = respx.delete(f"{ROOT}/requests/I240101_0001/documents/12345_abcdef").mock(
        return_value=httpx.Response(200)
    )
    async with AsyncEasyvistaClient(config) as client:
        result = await client.delete_document("I240101_0001", "12345_abcdef")
    assert route.call_count == 1
    assert result is None


@respx.mock
async def test_delete_document_top_level_path_style_addresses_the_document_by_id(
    config,
):
    """Both routes are declared in the instance's own OpenAPI document.

    Only the top-level one is marked ``deprecated`` there, so which one works
    is a profile question rather than a routing one. ``rfc_number`` has no slot
    in this route, hence ``None``.
    """
    route = respx.delete(f"{ROOT}/documents/12345_abcdef").mock(
        return_value=httpx.Response(200)
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.delete_document(None, "12345_abcdef", path_style="top_level")
    assert route.call_count == 1


@respx.mock
async def test_delete_document_takes_its_path_style_from_the_config(config):
    """The keyword defaults to the config field, so a deployment sets it once."""
    route = respx.delete(f"{ROOT}/documents/12345_abcdef").mock(
        return_value=httpx.Response(200)
    )
    top_level = dataclasses.replace(config, document_delete_path_style="top_level")
    async with AsyncEasyvistaClient(top_level) as client:
        await client.delete_document(None, "12345_abcdef")
    assert route.call_count == 1


@respx.mock
async def test_delete_document_accepts_a_document_record(config):
    """The id is read off the record, so a caller need not unpack it."""
    route = respx.delete(f"{ROOT}/requests/I240101_0001/documents/12345_abcdef").mock(
        return_value=httpx.Response(200)
    )
    document = Document.model_validate({"DOCUMENT_ID": "12345_abcdef"})
    async with AsyncEasyvistaClient(config) as client:
        await client.delete_document("I240101_0001", document)
    assert route.call_count == 1


@respx.mock
async def test_delete_document_rejects_a_document_without_an_id(config):
    """A record carrying no DOCUMENT_ID would address the collection."""
    route = respx.delete(f"{ROOT}/requests/I240101_0001/documents/").mock(
        return_value=httpx.Response(200)
    )
    document = Document.model_validate({"DOCUMENT": "report.pdf"})
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError, match="DOCUMENT_ID"):
            await client.delete_document("I240101_0001", document)
    assert route.call_count == 0


@respx.mock
async def test_get_department_comment_honours_a_memo_field_override(config):
    """The route's last segment is a memo-field selector, not a literal.

    In the instance OpenAPI document read 2026-08-27 it is a path *parameter*
    named ``comment``, and the sibling ``GET requests/{rfc_number}/{comment}``
    describes the same parameter as "Memo field type, could be comment,
    description". So a deployment whose department memo column is named
    differently is not locked out.
    """
    default_route = respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": "default"})
    )
    override = respx.get(f"{ROOT}/departments/60/comment_service").mock(
        return_value=httpx.Response(200, json={"COMMENT_SERVICE": "overridden"})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.get_department_comment(60, memo_field="comment_service")
    assert override.call_count == 1
    assert default_route.call_count == 0


@respx.mock
async def test_download_document_fetches_the_ddl_href(config):
    route = respx.get("https://ev.test/dl/7").mock(
        return_value=httpx.Response(200, content=b"\x89PNG\r\n\x1a\n binary")
    )
    doc = Document.model_validate(
        {"DOCUMENT": "shot.png", "DDL_HREF": "https://ev.test/dl/7"}
    )
    async with AsyncEasyvistaClient(config) as client:
        content = await client.download_document(doc)
    assert content == b"\x89PNG\r\n\x1a\n binary"
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
async def test_download_document_accepts_a_relative_path(config):
    respx.get(f"{ROOT}/documents/7/content").mock(
        return_value=httpx.Response(200, content=b"bytes")
    )
    async with AsyncEasyvistaClient(config) as client:
        assert await client.download_document("documents/7/content") == b"bytes"


async def test_download_document_refuses_a_foreign_download_url(config):
    doc = Document.model_validate({"DDL_HREF": "https://attacker.test/dl/7"})
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError, match="outside the configured instance"):
            await client.download_document(doc)


@respx.mock
async def test_stream_document_chunks_reassemble_to_the_download(config):
    # 3076 bytes at chunk_size=512: six full chunks and a 4-byte tail. Sized off
    # the boundary on purpose -- an exact multiple never exercises a short final
    # chunk, and reassembly passes either way.
    body = bytes(range(256)) * 12 + b"tail"
    respx.get("https://ev.test/dl/7").mock(
        return_value=httpx.Response(200, content=body)
    )
    doc = Document.model_validate(
        {"DOCUMENT": "big.bin", "DDL_HREF": "https://ev.test/dl/7"}
    )
    chunks = []
    async with AsyncEasyvistaClient(config) as client:
        async for chunk in client.stream_document(doc, chunk_size=512):
            chunks.append(chunk)
    assert b"".join(chunks) == body
    assert len(chunks) == 7, "the body arrived in one piece instead of streaming"
    assert len(chunks[-1]) == 4, "the short final chunk was padded or dropped"


class _ClosableStream(httpx.AsyncByteStream):
    """A response body that records when the transport closed it.

    ``closed`` flips in ``aclose()``/``close()``, which httpx calls when the
    response is
    released -- which is what ``stream_bytes`` does in its own ``finally``. So
    the flag answers "has the connection gone back to the pool yet".
    """

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._body

    async def aclose(self) -> None:
        self.closed = True


@respx.mock
async def test_stream_document_closes_the_inner_stream_when_stopped_early(config):
    """Stopping early releases the connection there and then, not eventually.

    ``stream_document`` hands out chunks from an inner ``stream_bytes``
    generator, and only *that* generator's ``finally`` closes the response and
    returns its connection to the httpx pool. Closing the outer generator
    unwinds its loop with ``GeneratorExit`` and does not close the inner one, so
    without the explicit close in ``stream_document`` the release waits for the
    inner generator to be collected -- and this asserts with no ``gc`` round and
    no scheduling hop in between. Until the release happens the connection stays
    checked out, which a caller with a small ``max_connections`` feels.

    Closing explicitly is also the only moment both client trees share: a caller
    that just stops iterating leaves the outer generator to be collected, and
    when that happens is a property of the runtime, not of this method.
    """
    stream = _ClosableStream(b"0123456789abcdef")
    respx.get("https://ev.test/dl/7").mock(
        return_value=httpx.Response(200, stream=stream)
    )
    doc = Document.model_validate({"DDL_HREF": "https://ev.test/dl/7"})
    async with AsyncEasyvistaClient(config) as client:
        chunks = client.stream_document(doc, chunk_size=8)
        assert await chunks.__anext__() == b"01234567"
        assert not stream.closed, "closed while the caller was still reading"
        await chunks.aclose()
        assert stream.closed, "the abandoned stream still holds its connection"


@respx.mock
async def test_stream_document_accepts_a_relative_path_like_download_document(config):
    """Same accepted inputs as download_document, resolved the same way."""
    respx.get(f"{ROOT}/documents/7/content").mock(
        return_value=httpx.Response(200, content=b"bytes")
    )
    path = "documents/7/content"
    async with AsyncEasyvistaClient(config) as client:
        streamed = [chunk async for chunk in client.stream_document(path)]
        downloaded = await client.download_document(path)
    assert b"".join(streamed) == downloaded == b"bytes"


@respx.mock
async def test_stream_document_and_download_document_agree_on_a_403(config):
    """One error mapping, not two: the streaming path must not soften a failure.

    Asserted as an equality between the paths rather than against a hardcoded
    type, so the two cannot drift apart without this failing -- which is the
    actual risk, since a streaming response needs its body read before the
    mapping can look at it at all.
    """
    respx.get("https://ev.test/dl/7").mock(
        return_value=httpx.Response(403, json={"error": "forbidden"})
    )
    doc = Document.model_validate({"DDL_HREF": "https://ev.test/dl/7"})
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError) as streamed:
            [chunk async for chunk in client.stream_document(doc)]
        with pytest.raises(EasyvistaError) as downloaded:
            await client.download_document(doc)
    assert type(streamed.value) is type(downloaded.value) is EasyvistaAuthError
    assert streamed.value.status_code == downloaded.value.status_code == 403
    assert streamed.value.ev_message == downloaded.value.ev_message == "forbidden"


async def test_stream_document_refuses_a_foreign_download_url(config):
    # The same-origin guard covers the streaming path too: it is a property of
    # the download, not of one method. Nothing is requested until iteration
    # begins, so the refusal lands on the first step.
    doc = Document.model_validate({"DDL_HREF": "https://attacker.test/dl/7"})
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError, match="outside the configured instance"):
            [chunk async for chunk in client.stream_document(doc)]


async def test_stream_document_needs_a_download_url(config):
    doc = Document.model_validate({"DOCUMENT": "orphan.txt"})
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError, match="no download URL"):
            [chunk async for chunk in client.stream_document(doc)]


# --- pagination --------------------------------------------------------------


def _paged_tickets_responder(request):
    offset = int(request.url.params.get("offset", "0"))
    if offset == 0:
        return httpx.Response(
            200,
            json={
                "records": [{"RFC_NUMBER": "I1"}, {"RFC_NUMBER": "I2"}],
                "record_count": 2,
                "total_record_count": 3,
                "@next": f"{ROOT}/requests?offset=2&max_rows=2",
            },
        )
    return httpx.Response(
        200,
        json={
            "records": [{"RFC_NUMBER": "I3"}],
            "record_count": 1,
            "total_record_count": 3,
        },
    )


@respx.mock
async def test_iter_tickets_follows_pages(config):
    respx.get(f"{ROOT}/requests").mock(side_effect=_paged_tickets_responder)
    async with AsyncEasyvistaClient(config) as client:
        rfcs = [t.rfc_number async for t in client.iter_tickets(page_size=2)]
    assert rfcs == ["I1", "I2", "I3"]


@respx.mock
async def test_iter_tickets_respects_max_records(config):
    route = respx.get(f"{ROOT}/requests").mock(side_effect=_paged_tickets_responder)
    async with AsyncEasyvistaClient(config) as client:
        rfcs = [
            t.rfc_number async for t in client.iter_tickets(page_size=2, max_records=1)
        ]
    assert rfcs == ["I1"]
    # Stops after the first page once the cap is hit (no second request).
    assert route.calls.last.request.url.params["offset"] == "0"


@respx.mock
async def test_iter_tickets_stops_on_empty_page(config):
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        assert [t async for t in client.iter_tickets(page_size=2)] == []


@respx.mock
async def test_iter_assets_follows_pages(config):
    def responder(request):
        offset = int(request.url.params.get("offset", "0"))
        if offset == 0:
            return httpx.Response(
                200,
                json={
                    "records": [{"ASSET_TAG": "A1"}, {"ASSET_TAG": "A2"}],
                    "record_count": 2,
                    "total_record_count": 3,
                    "@next": f"{ROOT}/assets?offset=2&max_rows=2",
                },
            )
        return httpx.Response(
            200,
            json={
                "records": [{"ASSET_TAG": "A3"}],
                "record_count": 1,
                "total_record_count": 3,
            },
        )

    respx.get(f"{ROOT}/assets").mock(side_effect=responder)
    async with AsyncEasyvistaClient(config) as client:
        tags = [a.asset_tag async for a in client.iter_assets(page_size=2)]
    assert tags == ["A1", "A2", "A3"]


@respx.mock
async def test_iter_employees_follows_pages(config):
    def responder(request):
        offset = int(request.url.params.get("offset", "0"))
        if offset == 0:
            return httpx.Response(
                200,
                json={
                    "records": [{"EMPLOYEE_ID": 1}, {"EMPLOYEE_ID": 2}],
                    "record_count": 2,
                    "total_record_count": 3,
                    "@next": f"{ROOT}/employees?offset=2&max_rows=2",
                },
            )
        return httpx.Response(
            200,
            json={
                "records": [{"EMPLOYEE_ID": 3}],
                "record_count": 1,
                "total_record_count": 3,
            },
        )

    respx.get(f"{ROOT}/employees").mock(side_effect=responder)
    async with AsyncEasyvistaClient(config) as client:
        ids = [e.employee_id async for e in client.iter_employees(page_size=2)]
    assert ids == [1, 2, 3]


@respx.mock
async def test_iter_employees_respects_max_records(config):
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"EMPLOYEE_ID": 1}, {"EMPLOYEE_ID": 2}],
                "record_count": 2,
                "total_record_count": 5,
                "@next": f"{ROOT}/employees?offset=2&max_rows=2",
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        ids = [
            e.employee_id
            async for e in client.iter_employees(page_size=2, max_records=1)
        ]
    assert ids == [1]


@respx.mock
async def test_iter_departments_paginates(config):
    respx.get(f"{ROOT}/departments").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "records": [{"DEPARTMENT_ID": 1}],
                    "@next": f"{ROOT}/departments?offset=1",
                },
            ),
            httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 2}]}),
        ]
    )
    async with AsyncEasyvistaClient(config) as client:
        ids = [d.department_id async for d in client.iter_departments(page_size=1)]
    assert ids == [1, 2]


def _paged_actions_responder(request):
    offset = int(request.url.params.get("offset", "0"))
    if offset == 0:
        return httpx.Response(
            200,
            json={
                "records": [{"ACTION_ID": 1}, {"ACTION_ID": 2}],
                "record_count": 2,
                "total_record_count": 3,
                "@next": f"{ROOT}/actions?offset=2&max_rows=2",
            },
        )
    return httpx.Response(
        200,
        json={
            "records": [{"ACTION_ID": 3}],
            "record_count": 1,
            "total_record_count": 3,
        },
    )


@respx.mock
async def test_iter_actions_crosses_the_page_list_actions_stops_at(config):
    """``list_actions`` truncates a busy ticket's log silently; this does not."""
    respx.get(f"{ROOT}/actions").mock(side_effect=_paged_actions_responder)
    async with AsyncEasyvistaClient(config) as client:
        ids = [a.action_id async for a in client.iter_actions("I1", page_size=2)]
    assert ids == [1, 2, 3]


@respx.mock
async def test_iter_actions_keeps_the_ticket_filter_on_every_page(config):
    """A page-2 request that lost the filter would sweep every ticket's log."""
    route = respx.get(f"{ROOT}/actions").mock(side_effect=_paged_actions_responder)
    async with AsyncEasyvistaClient(config) as client:
        [a async for a in client.iter_actions("I1", page_size=2)]
    assert len(route.calls) == 2
    for call in route.calls:
        assert call.request.url.params["search"] == 'REQUEST.RFC_NUMBER:"I1"'


@respx.mock
async def test_iter_actions_respects_max_records(config):
    route = respx.get(f"{ROOT}/actions").mock(side_effect=_paged_actions_responder)
    async with AsyncEasyvistaClient(config) as client:
        ids = [
            a.action_id
            async for a in client.iter_actions("I1", page_size=2, max_records=1)
        ]
    assert ids == [1]
    # Stops inside the first page once the cap is hit (no second request).
    assert len(route.calls) == 1


@respx.mock
async def test_iter_actions_stops_when_the_server_reports_no_next_page(config):
    """No ``@next`` ends the sweep even on a page that filled ``page_size``."""
    route = respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"ACTION_ID": 1}, {"ACTION_ID": 2}],
                "record_count": 2,
                "total_record_count": 2,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        ids = [a.action_id async for a in client.iter_actions("I1", page_size=2)]
    assert ids == [1, 2]
    assert len(route.calls) == 1


@respx.mock
async def test_iter_actions_forwards_a_fields_projection(config):
    route = respx.get(f"{ROOT}/actions").mock(side_effect=_paged_actions_responder)
    async with AsyncEasyvistaClient(config) as client:
        [
            a
            async for a in client.iter_actions(
                "I1", fields=["ACTION_ID", "ACTION_LABEL_FR"], page_size=2
            )
        ]
    assert route.calls[0].request.url.params["fields"] == "ACTION_ID,ACTION_LABEL_FR"


async def test_iter_actions_refuses_a_blank_rfc(config):
    """An unfiltered sweep of every ticket's actions is never the intent."""
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError):
            [a async for a in client.iter_actions("")]


# --- statistics --------------------------------------------------------------


def _stats_responder(request):
    # Two pages of tickets so the test also exercises iter pagination.
    offset = int(request.url.params.get("offset", "0"))
    if offset == 0:
        return httpx.Response(
            200,
            json={
                "records": [
                    {"RFC_NUMBER": "I1", "STATUS": {"STATUS_EN": "Open"}},
                    {"RFC_NUMBER": "I2", "STATUS": {"STATUS_EN": "Closed"}},
                ],
                "record_count": 2,
                "total_record_count": 3,
                "@next": f"{ROOT}/requests?offset=2&max_rows=2",
            },
        )
    return httpx.Response(
        200,
        json={
            "records": [{"RFC_NUMBER": "I3", "STATUS": {"STATUS_EN": "Open"}}],
            "record_count": 1,
            "total_record_count": 3,
        },
    )


@respx.mock
async def test_ticket_statistics_aggregates_across_pages(config):
    """No longer routes through ``iter_tickets``.

    ``iter_tickets`` yields records one at a time and discards the envelope, so
    it cannot also hand back ``total_record_count`` -- the one number that says
    how large the population a capped aggregation sampled actually was.
    ``_collect_tickets`` walks the same offsets and issues the same requests.
    """
    from easyvista_python_client import TicketStatistics

    respx.get(f"{ROOT}/requests").mock(side_effect=_stats_responder)
    async with AsyncEasyvistaClient(config) as client:
        stats = await client.ticket_statistics(dimensions=["STATUS"])
    assert isinstance(stats, TicketStatistics)
    assert stats.total == 3
    assert stats.breakdowns["STATUS"] == {"Open": 2, "Closed": 1}
    assert stats.truncated is False
    assert stats.population_total == 3


@respx.mock
async def test_ticket_statistics_passes_languages_through_to_the_aggregator(config):
    # Proves the keyword reaches aggregate_tickets on the real dispatch path,
    # not just in the pure function's own tests.
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {
                        "RFC_NUMBER": "I1",
                        "STATUS": {"STATUS_EN": "[Open]", "STATUS_FR": "Ouvert"},
                    }
                ],
                "record_count": 1,
                "total_record_count": 1,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        default = await client.ticket_statistics(dimensions=["STATUS"])
        french = await client.ticket_statistics(
            dimensions=["STATUS"], languages=("_FR",)
        )
    # The bracketed English echo loses to the real French sibling by default...
    assert default.breakdowns["STATUS"] == {"Ouvert": 1}
    # ...and asking for French directly reaches the same column.
    assert french.breakdowns["STATUS"] == {"Ouvert": 1}


@respx.mock
async def test_ticket_statistics_respects_max_records(config):
    """The cap truncating is now disclosed rather than silent.

    That is the whole point of the two new fields: ``total == 1`` describes a
    sample of one out of three, and before this a caller had no way to tell
    that from a population of one.
    """
    respx.get(f"{ROOT}/requests").mock(side_effect=_stats_responder)
    async with AsyncEasyvistaClient(config) as client:
        stats = await client.ticket_statistics(dimensions=["STATUS"], max_records=1)
    assert stats.total == 1  # capped before the second page
    assert stats.truncated is True
    assert stats.population_total == 3


@respx.mock
async def test_ticket_statistics_requests_field_projection(config):
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={"records": [], "record_count": 0, "total_record_count": 0},
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.ticket_statistics(dimensions=["URGENCY"])
    fields = route.calls.last.request.url.params["fields"]
    assert "URGENCY_ID" in fields and "RFC_NUMBER" in fields


@respx.mock
async def test_ticket_statistics_materialises_the_page_before_aggregating(
    config, monkeypatch
):
    """``aggregate_tickets`` is handed a real list, never a live stream.

    The page is collected first because ``aggregate_tickets`` consumes a plain
    iterable, and on one surface ``iter_tickets`` is an async generator it
    cannot take at all. Asserting on ``stats.total`` alone would pass against a
    streaming form too -- the number comes out the same either way -- so this
    spies on what the function was actually handed.
    """
    handed: list[object] = []
    real = client_module.aggregate_tickets

    def spy(tickets, **kwargs):
        handed.append(tickets)
        return real(tickets, **kwargs)

    monkeypatch.setattr(client_module, "aggregate_tickets", spy)
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"RFC_NUMBER": "I1"}],
                "record_count": 1,
                "total_record_count": 1,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        stats = await client.ticket_statistics(max_records=1)
    assert stats.total == 1
    assert isinstance(handed[0], list)
    assert [t.rfc_number for t in handed[0]] == ["I1"]


# --- memos, departments, employees -------------------------------------------


@respx.mock
async def test_resolve_memo_relative_path_and_full_url(config):
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "<p>hi</p>", "HREF": "x"})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": ""})
    )
    async with AsyncEasyvistaClient(config) as client:
        assert await client.resolve_memo("requests/I1/description") == "<p>hi</p>"
        # Full URL (as returned in a record's link) resolves too; empty note -> "".
        note = await client.resolve_memo(f"{ROOT}/departments/60/comment_department")
    assert note == ""


@respx.mock
async def test_get_department_and_comment(config):
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(
            200, json={"records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_FR": "ACME CORP"}]}
        )
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": ""})
    )
    async with AsyncEasyvistaClient(config) as client:
        dept = await client.get_department(60)
        note = await client.get_department_comment(60)
    assert isinstance(dept, Department)
    assert dept.name == "ACME CORP"
    assert note == ""  # empty note distinguished from a 403


@respx.mock
async def test_find_departments_fast_path_by_code(config):
    route = respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_CODE": "ACME-CORP"}],
                "total_record_count": 1,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("ACME-CORP")
    assert [d.department_id for d in found] == [60]
    search = route.calls.last.request.url.params["search"]
    assert search == 'DEPARTMENT_CODE:"ACME-CORP"'


@respx.mock
async def test_find_departments_auto_tries_code_before_id(config):
    """An all-digit name is a candidate CODE before it is a candidate ID.

    It used to go straight to ``DEPARTMENT_ID``, so a department whose CODE is
    all digits was looked up as an id and a **different** department came back
    with HTTP 200 and no hint. Code first fixes that; the id lookup still
    happens, one request later, when no such code exists.
    """
    route = respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_CODE": "ACME-CORP"}],
                "total_record_count": 1,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("60")
    assert [d.department_id for d in found] == [60]
    assert route.calls.last.request.url.params["search"] == 'DEPARTMENT_CODE:"60"'
    assert route.call_count == 1


@respx.mock
async def test_find_departments_auto_falls_back_to_id_for_an_all_digit_name(config):
    """The regression guard for the wrong-record bug.

    When the digits are an id and not a code, the code lookup misses and the id
    lookup runs -- one extra round trip, on a path the fast path only ever was
    an optimization for.
    """
    empty = httpx.Response(200, json={"records": [], "total_record_count": 0})
    hit = httpx.Response(
        200,
        json={"records": [{"DEPARTMENT_ID": 60}], "total_record_count": 1},
    )
    route = respx.get(f"{ROOT}/departments").mock(side_effect=[empty, hit])
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("60")
    assert [d.department_id for d in found] == [60]
    assert route.call_count == 2
    searches = [call.request.url.params["search"] for call in route.calls]
    assert searches == ['DEPARTMENT_CODE:"60"', 'DEPARTMENT_ID:"60"']


@respx.mock
async def test_find_departments_by_pins_a_single_column(config):
    """``by`` restores the old lookup exactly, or skips the fast path entirely.

    ``by="DEPARTMENT_ID"`` must be read as ONE column, not as eleven
    single-character ones -- ``str`` satisfies ``Sequence[str]``, so the string
    branch is checked first.
    """
    route = respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(
            200,
            json={"records": [{"DEPARTMENT_ID": 60}], "total_record_count": 1},
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("60", by="DEPARTMENT_ID")
    assert [d.department_id for d in found] == [60]
    assert route.call_count == 1
    assert route.calls.last.request.url.params["search"] == 'DEPARTMENT_ID:"60"'

    # `by=[]` skips the fast path: the only call is the fuzzy scan's own
    # unfiltered sweep.
    route.reset()
    async with AsyncEasyvistaClient(config) as client:
        await client.find_departments("60", by=[])
    assert "search" not in route.calls.last.request.url.params


@respx.mock
async def test_find_departments_fuzzy_fallback(config):
    # Fast path (exact code) misses, then the fuzzy scan matches
    # "ACME CORP" ~ "acmecorp".
    respx.get(f"{ROOT}/departments").mock(
        side_effect=[
            httpx.Response(
                200, json={"records": [], "total_record_count": 0}
            ),  # fast path: no exact code
            httpx.Response(
                200,
                json={"records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_FR": "ACME CORP"}]},
            ),  # iter page 1
        ]
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("acmecorp", limit=5)
    assert [d.department_id for d in found] == [60]


@respx.mock
async def test_find_departments_fuzzy_scan_truncates_to_limit(config):
    # The fast-path code miss, then a single fuzzy-scan page with three
    # matches ("acmecorp" is a substring of all three labels); limit=2 must stop
    # at 2 without requiring a second page.
    respx.get(f"{ROOT}/departments").mock(
        side_effect=[
            httpx.Response(200, json={"records": [], "total_record_count": 0}),
            httpx.Response(
                200,
                json={
                    "records": [
                        {"DEPARTMENT_ID": 60, "DEPARTMENT_FR": "ACME CORP"},
                        {"DEPARTMENT_ID": 61, "DEPARTMENT_FR": "ACME CORP 2"},
                        {"DEPARTMENT_ID": 62, "DEPARTMENT_FR": "ACME CORP 3"},
                    ],
                    "total_record_count": 3,
                },
            ),
        ]
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("acmecorp", limit=2)
    assert [d.department_id for d in found] == [60, 61]


@respx.mock
async def test_find_departments_fast_path_truncates_to_limit(config):
    # The fast-path (exact ID/code) hit itself can return more records than
    # limit; the truncation must apply there too, without any fuzzy fallback.
    respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {"DEPARTMENT_ID": 1, "DEPARTMENT_CODE": "DUP"},
                    {"DEPARTMENT_ID": 2, "DEPARTMENT_CODE": "DUP"},
                    {"DEPARTMENT_ID": 3, "DEPARTMENT_CODE": "DUP"},
                ],
                "total_record_count": 3,
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("DUP", limit=1)
    assert [d.department_id for d in found] == [1]


@respx.mock
async def test_find_departments_no_match_returns_empty(config):
    respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(200, json={"records": [], "total_record_count": 0})
    )
    async with AsyncEasyvistaClient(config) as client:
        assert await client.find_departments("ghost") == []


@respx.mock
async def test_find_departments_empty_needle_returns_empty_not_everything(config):
    # "-" and "   " both normalize to "" ; without the empty-needle guard,
    # `_department_matches` treats "" as a substring of every string field, so
    # the fuzzy scan would wrongly return every department it saw.
    def _responder(request):
        if "search" in request.url.params:
            return httpx.Response(200, json={"records": [], "total_record_count": 0})
        # Only reached if the guard is missing; a benign department that would
        # incorrectly "match" any empty needle.
        return httpx.Response(
            200, json={"records": [{"DEPARTMENT_ID": 1, "DEPARTMENT_CODE": "ABC"}]}
        )

    route = respx.get(f"{ROOT}/departments").mock(side_effect=_responder)
    async with AsyncEasyvistaClient(config) as client:
        assert await client.find_departments("-") == []
        assert await client.find_departments("   ") == []
    # The guard short-circuits after the fast-path miss, before iter_departments
    # ever issues its fuzzy-scan request. "-" still trips one fast-path call
    # (it survives .strip()); "   " is blank after stripping, so ev_equals_filter
    # returns None and no request is sent for it at all — hence 1, not 2.
    assert route.call_count == 1


@respx.mock
async def test_find_departments_rejects_comma_injection(config):
    """A ',' injection must not silently widen the result set.

    ',' is a live EasyVista combinator (OR within one field), so
    find_departments('A",DEPARTMENT_CODE:"B') would emit
    DEPARTMENT_CODE:"A",DEPARTMENT_CODE:"B" and return BOTH departments.
    Verified live: returns 2 instead of 1, with no error.
    """
    route = respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {"DEPARTMENT_ID": 1, "DEPARTMENT_CODE": "ALPHA"},
                    {"DEPARTMENT_ID": 2, "DEPARTMENT_CODE": "BETA"},
                ]
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments('ALPHA",DEPARTMENT_CODE:"BETA')
    # The injected name matches no real department, so nothing should come back.
    assert found == []
    # The unsafe value must never reach the server as a filter.
    for call in route.calls:
        assert '"' not in (call.request.url.params.get("search") or "")


@respx.mock
async def test_get_and_search_employees(config):
    respx.get(f"{ROOT}/employees/6087").mock(
        return_value=httpx.Response(
            200, json={"records": [{"EMPLOYEE_ID": 6087, "LAST_NAME": "Doe"}]}
        )
    )
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(
            200, json={"records": [{"EMPLOYEE_ID": 6087}], "total_record_count": 1}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        emp = await client.get_employee(6087)
        result = await client.search_employees(search='DEPARTMENT_ID:"60"')
    assert isinstance(emp, Employee)
    assert emp.last_name == "Doe"
    assert result.records[0].employee_id == 6087


@respx.mock
async def test_update_employee(config):
    respx.put(f"{ROOT}/employees/9001").mock(
        return_value=httpx.Response(200, json={"records": [{"EMPLOYEE_ID": 9001}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        emp = await client.update_employee(9001, EmployeeUpdate(phone_number="0102"))
    assert emp.employee_id == 9001


@respx.mock
async def test_create_department_and_employee(config):
    # Envelope-wrapped POST bodies for create, a bare payload for the PUT update.
    dep_route = respx.post(f"{ROOT}/departments").mock(
        return_value=httpx.Response(200, json={"HREF": f"{ROOT}/departments/61"})
    )
    emp_route = respx.post(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"HREF": f"{ROOT}/employees/9001"})
    )
    respx.put(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        dept = await client.create_department(PostDepartment(department_code="NEW"))
        emp = await client.create_employee(PostEmployee(last_name="Doe"))
        updated = await client.update_department(60, DepartmentUpdate(manager_id=42))
    assert dept.href.endswith("/departments/61")
    assert emp.href.endswith("/employees/9001")
    assert updated.department_id == 60
    # Parse the sent body (robust to JSON separator/key-order details).
    assert json.loads(dep_route.calls.last.request.content) == {
        "departments": [{"department_code": "NEW"}]
    }
    assert json.loads(emp_route.calls.last.request.content) == {
        "employees": [{"last_name": "Doe"}]
    }


# --- ticket context ----------------------------------------------------------


@respx.mock
async def test_get_ticket_context_assembles_bundle(config):
    from easyvista_python_client import TicketContext

    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1", "TITLE": "T"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "<p>hi</p>"})
    )
    respx.get(f"{ROOT}/requests/I1/comment").mock(
        return_value=httpx.Response(200, json={"COMMENT": "note"})
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": []})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"documents": []})
    )

    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_ticket_context("I1")

    assert isinstance(ctx, TicketContext)
    assert ctx.ticket.rfc_number == "I1"
    assert ctx.description == "<p>hi</p>"
    assert ctx.comment == "note"
    assert ctx.to_markdown().startswith("# Ticket")
    assert "/api/" not in ctx.to_markdown()


@respx.mock
async def test_get_ticket_context_degrades_on_missing_subresources(config):
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(404, json={})
    )
    respx.get(f"{ROOT}/requests/I1/comment").mock(
        return_value=httpx.Response(404, json={})
    )
    respx.get(f"{ROOT}/actions").mock(return_value=httpx.Response(403, json={}))
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(403, json={})
    )

    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_ticket_context("I1")

    assert ctx.description is None
    assert ctx.comment is None
    assert ctx.actions == []
    assert ctx.documents == []
    # Each swallow is now recorded, so `[]` is distinguishable from "forbidden".
    assert ctx.degraded == frozenset(
        {
            "memo:description:404",
            "memo:comment:404",
            "actions:403",
            "documents:403",
        }
    )


@respx.mock
async def test_get_ticket_context_still_raises_on_a_404_from_a_list_call(config):
    """The asymmetry between the two except clauses is load-bearing.

    The memos degrade on 404 *and* 403, while the two list calls catch
    ``EasyvistaAuthError`` ONLY -- so a 404 there still fails the bundle. Adding
    the degraded-recording line inside each clause must not have widened either
    caught tuple. This test reddens if a later tidy-up merges them.
    """
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    for memo in ("description", "comment"):
        respx.get(f"{ROOT}/requests/I1/{memo}").mock(
            return_value=httpx.Response(404, json={})
        )
    respx.get(f"{ROOT}/actions").mock(return_value=httpx.Response(404, json={}))
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaNotFound):
            await client.get_ticket_context("I1")


@respx.mock
async def test_ticket_context_resolves_action_bodies(config):
    # The defect this fixes: list_actions never returns DESCRIPTION, so the
    # rendered Markdown had empty action bodies. The context now fetches each
    # action item-level and resolves its DESCRIPTION memo.
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1", "TITLE": "T"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "the ticket body"})
    )
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": [{"ACTION_ID": 7}]})
    )
    respx.get(f"{ROOT}/actions/7").mock(
        return_value=httpx.Response(
            200,
            json={
                "ACTION_ID": 7,
                "DESCRIPTION": {"HREF": f"{ROOT}/actions/7/description"},
            },
        )
    )
    respx.get(f"{ROOT}/actions/7/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "<p>the note</p>"})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1")
    assert context.actions[0].description == "<p>the note</p>"
    assert "the note" in context.to_markdown()


@respx.mock
async def test_ticket_context_can_skip_resolving_action_bodies(config):
    # Opt-out: resolving costs two extra requests per action, and a ticket on
    # this instance carries ~11 workflow-generated actions.
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    item = respx.get(f"{ROOT}/actions/7").mock(
        return_value=httpx.Response(200, json={"ACTION_ID": 7})
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": [{"ACTION_ID": 7}]})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1", resolve_action_bodies=False)
    assert item.call_count == 0
    assert [a.action_id for a in context.actions] == [7]


@respx.mock
async def test_ticket_context_tolerates_an_unreadable_action(config):
    # A 403 on one action must not fail the whole bundle -- the same degradation
    # rule the rest of get_ticket_context follows. The unreadable action stays
    # in the bundle unresolved (a profile restriction must never silently
    # shorten a ticket's history) and its readable neighbour still resolves.
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(
            200, json={"actions": [{"ACTION_ID": 7}, {"ACTION_ID": 8}]}
        )
    )
    respx.get(f"{ROOT}/actions/7").mock(return_value=httpx.Response(403))
    respx.get(f"{ROOT}/actions/8").mock(
        return_value=httpx.Response(
            200,
            json={
                "ACTION_ID": 8,
                "DESCRIPTION": {"HREF": f"{ROOT}/actions/8/description"},
            },
        )
    )
    respx.get(f"{ROOT}/actions/8/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "the note"})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1")
    assert [a.action_id for a in context.actions] == [7, 8]
    assert context.actions[0].description is None
    assert context.actions[1].description == "the note"


@respx.mock
async def test_ticket_context_resolves_comment_when_description_is_empty(config):
    # The EasyVista UI shows ONE text field per action, headed "comment or
    # description": it renders DESCRIPTION and falls back to COMMENT only when
    # DESCRIPTION is empty (measured in the UI 2026-09-01 on one instance,
    # Service Manager 2025.3 -- one instance, one date, may not generalise).
    # Resolving DESCRIPTION alone therefore loses the body of exactly the
    # actions a human CAN read: this bundle must carry the COMMENT text.
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": [{"ACTION_ID": 9}]})
    )
    respx.get(f"{ROOT}/actions/9").mock(
        return_value=httpx.Response(
            200,
            json={
                "ACTION_ID": 9,
                "DESCRIPTION": {"HREF": f"{ROOT}/actions/9/description"},
                "COMMENT": {"HREF": f"{ROOT}/actions/9/comment"},
            },
        )
    )
    # DESCRIPTION resolves EMPTY -- the shadow-fallback case.
    respx.get(f"{ROOT}/actions/9/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": ""})
    )
    comment = respx.get(f"{ROOT}/actions/9/comment").mock(
        return_value=httpx.Response(
            200, json={"COMMENT": "what the user actually reads"}
        )
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1")
    assert comment.call_count == 1
    assert context.actions[0].comment == "what the user actually reads"
    # ...and it must survive into the rendered document, not just the model.
    assert "what the user actually reads" in context.to_markdown()


@respx.mock
async def test_ticket_context_does_not_fetch_comment_when_description_has_text(config):
    # The third request is conditional: DESCRIPTION wins in the UI, so a
    # populated description makes the COMMENT memo dead weight. Resolving it
    # anyway would add one request per action on every ticket.
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": [{"ACTION_ID": 9}]})
    )
    respx.get(f"{ROOT}/actions/9").mock(
        return_value=httpx.Response(
            200,
            json={
                "ACTION_ID": 9,
                "DESCRIPTION": {"HREF": f"{ROOT}/actions/9/description"},
                "COMMENT": {"HREF": f"{ROOT}/actions/9/comment"},
            },
        )
    )
    respx.get(f"{ROOT}/actions/9/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "the visible note"})
    )
    comment = respx.get(f"{ROOT}/actions/9/comment").mock(
        return_value=httpx.Response(200, json={"COMMENT": "shadowed, never rendered"})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1")
    assert comment.call_count == 0
    assert context.actions[0].description == "the visible note"
    assert "shadowed, never rendered" not in context.to_markdown()


@respx.mock
async def test_ticket_context_tolerates_an_action_that_has_vanished(config):
    # The 404 arm of the same except clause -- an action listed but deleted
    # before we fetch it item-level. Without this case the clause could be
    # narrowed to EasyvistaAuthError alone and the suite would stay green.
    # The vanished action keeps its slot: degrading must never shorten a
    # ticket's history behind the caller's back.
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(
            200, json={"actions": [{"ACTION_ID": 7}, {"ACTION_ID": 8}]}
        )
    )
    respx.get(f"{ROOT}/actions/7").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions/8").mock(
        return_value=httpx.Response(200, json={"ACTION_ID": 8})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1")
    assert [a.action_id for a in context.actions] == [7, 8]
    assert context.actions[0].description is None


@respx.mock
async def test_ticket_context_keeps_an_action_that_has_no_id(config):
    # A listed action with neither ACTION_ID nor a numeric HREF tail has
    # nothing to fetch item-level, so it passes through untouched. Without the
    # short-circuit the client would request `actions/None` (here: an unmocked
    # route) instead of degrading.
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(
            200,
            json={"actions": [{"HREF": f"{ROOT}/requests/I1"}, {"ACTION_ID": 8}]},
        )
    )
    item = respx.get(f"{ROOT}/actions/8").mock(
        return_value=httpx.Response(200, json={"ACTION_ID": 8})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1")
    assert [a.action_id for a in context.actions] == [None, 8]
    assert item.call_count == 1


@respx.mock
async def test_ticket_context_lists_documents_before_resolving_action_bodies(config):
    """The documents list is fetched inside the bundle, not after it.

    ``_resolve_action_bodies`` runs strictly after the bundle settles, so the
    documents request is always on the wire before the first action-body one.
    The pre-migration sequential client fetched documents last, after every
    action was resolved: same requests, same results, different order on the
    wire. That reordering is the accepted delta, and this pins it.
    """
    seen: list[str] = []

    def record(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"records": [{"ACTION_ID": 7}]})

    respx.route().mock(side_effect=record)
    async with AsyncEasyvistaClient(config) as client:
        await client.get_ticket_context("I1")

    documents = next(i for i, p in enumerate(seen) if p.endswith("/documents"))
    actions_item = next(i for i, p in enumerate(seen) if p.endswith("/actions/7"))
    assert documents < actions_item


@respx.mock
async def test_get_ticket_context_resolves_the_two_default_memos(config):
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "body"})
    )
    respx.get(f"{ROOT}/requests/I1/comment").mock(
        return_value=httpx.Response(200, json={"COMMENT": "note"})
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": []})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"documents": []})
    )

    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_ticket_context("I1", resolve_action_bodies=False)

    assert ctx.memos == {"description": "body", "comment": "note"}
    assert ctx.description == "body"
    assert ctx.comment == "note"


@respx.mock
async def test_get_ticket_context_honours_custom_memo_fields(config):
    """An instance whose body memo is neither default is reached by naming it."""
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    solution = respx.get(f"{ROOT}/requests/I1/solution").mock(
        return_value=httpx.Response(200, json={"SOLUTION": "fixed it"})
    )
    description = respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "unused"})
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": []})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"documents": []})
    )

    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_ticket_context(
            "I1", resolve_action_bodies=False, memo_fields=("solution",)
        )

    assert ctx.memos == {"solution": "fixed it"}
    assert ctx.description is None
    assert ctx.comment is None
    assert solution.called
    # The default memos are not fetched when they were not asked for.
    assert not description.called


@respx.mock
async def test_get_ticket_context_empty_memo_fields_skips_memo_resolution(config):
    """The empty-tuple boundary: no memo sub-resource is requested at all.

    Pins the ``settle`` slicing arithmetic -- ``memo_results[: len(memo_fields)]``
    and ``memo_results[len(memo_fields) :]`` -- at ``len(memo_fields) == 0``, so a
    future rewrite of that slicing cannot silently break this case.
    """
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": []})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"documents": []})
    )

    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_ticket_context(
            "I1", resolve_action_bodies=False, memo_fields=()
        )

    assert ctx.memos == {}
    assert ctx.description is None
    assert ctx.comment is None
    assert ctx.actions == []
    assert ctx.documents == []


# --- department context ------------------------------------------------------


@respx.mock
async def test_get_department_context_full_assembly(config):
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(
            200, json={"records": [{"DEPARTMENT_ID": 60, "MANAGER_ID": 42}]}
        )
    )
    respx.get(f"{ROOT}/employees/42").mock(
        return_value=httpx.Response(
            200, json={"records": [{"EMPLOYEE_ID": 42, "LAST_NAME": "Boss"}]}
        )
    )
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": [{"EMPLOYEE_ID": 1}]})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": "team note"})
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"RFC_NUMBER": "I1", "STATUS_ID": 2}],
                "total_record_count": 5,
            },
        )
    )
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(200, json={"records": [{"ASSET_ID": 7}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(60, recent_tickets=1)
    assert isinstance(ctx, DepartmentContext)
    assert ctx.department.department_id == 60
    assert ctx.manager.last_name == "Boss"
    assert ctx.note == "team note"
    assert ctx.ticket_count == 5
    assert ctx.employees[0].employee_id == 1
    assert ctx.assets[0].asset_id == 7
    assert ctx.ticket_statistics is not None


@respx.mock
async def test_get_department_context_honours_memo_fields(config):
    """``memo_fields`` threads the same memo selector through the bundle.

    A sequence rather than a single name, mirroring
    :meth:`get_ticket_context`'s own ``memo_fields``: every resolved memo lands
    in ``memos`` and ``note`` is the first with text. The read stays wrapped in
    the bundle's 403/404 degradation, unlike :meth:`get_department_comment`,
    which raises -- swapping that would change the bundle's failure semantics,
    not just its route.
    """
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    default_route = respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": "default"})
    )
    override = respx.get(f"{ROOT}/departments/60/comment_service").mock(
        return_value=httpx.Response(200, json={"COMMENT_SERVICE": "overridden"})
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(
            60, resolve_manager=False, memo_fields=("comment_service",)
        )
    assert ctx.note == "overridden"
    assert ctx.memos == {"comment_service": "overridden"}
    assert override.call_count == 1
    assert default_route.call_count == 0


def _department_bundle_mocks(ticket_route_json=None):
    """Mock every branch of the department bundle with an empty-but-valid page.

    Returns the ``/requests`` route so a caller can inspect the parameters the
    recent-tickets and statistics sweeps sent.
    """
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": "note"})
    )
    return respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json=ticket_route_json
            or {"records": [], "record_count": 0, "total_record_count": 0},
        )
    )


@respx.mock
async def test_get_department_context_projects_and_sorts_recent_tickets(config):
    """The one deliberate default change, pinned at the request level.

    Sending no projection is not neutral: on the verified instance the default
    list projection returns TITLE present but EMPTY, so every recent ticket's
    ``.title`` was ``None`` for every caller. The default now projects.
    """
    route = _department_bundle_mocks()
    async with AsyncEasyvistaClient(config) as client:
        await client.get_department_context(60, resolve_manager=False)
    sweeps = [
        call.request.url.params
        for call in route.calls
        if call.request.url.params.get("sort")
    ]
    assert len(sweeps) == 1
    assert sweeps[0]["sort"] == "RFC_NUMBER DESC"
    assert "TITLE" in sweeps[0]["fields"]


@respx.mock
async def test_get_department_context_forwards_a_caller_projection_and_sort(config):
    """``ticket_fields=None`` restores the exact previous request."""
    route = _department_bundle_mocks()
    async with AsyncEasyvistaClient(config) as client:
        await client.get_department_context(
            60,
            resolve_manager=False,
            include_statistics=False,
            ticket_fields=["RFC_NUMBER"],
            recent_tickets_sort=None,
        )
    params = route.calls.last.request.url.params
    assert params["fields"] == "RFC_NUMBER"
    assert "sort" not in params

    route.reset()
    async with AsyncEasyvistaClient(config) as client:
        await client.get_department_context(
            60,
            resolve_manager=False,
            include_statistics=False,
            ticket_fields=None,
        )
    assert "fields" not in route.calls.last.request.url.params


@respx.mock
async def test_get_department_context_caps_the_statistics_sample(config):
    """``statistics_max_records`` was inherited silently from
    ``ticket_statistics``; it is a keyword now, and the truncation is
    disclosed."""
    _department_bundle_mocks(
        {
            "records": [{"RFC_NUMBER": "I1"}, {"RFC_NUMBER": "I2"}],
            "record_count": 2,
            "total_record_count": 2,
        }
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(
            60, resolve_manager=False, statistics_max_records=1, dimensions=["STATUS"]
        )
    assert ctx.ticket_statistics is not None
    assert ctx.ticket_statistics.total == 1
    assert ctx.ticket_statistics.truncated is True
    assert ctx.ticket_statistics.population_total == 2


@pytest.mark.parametrize("status", [403, 404])
@respx.mock
async def test_get_department_context_records_degraded_branches(config, status):
    """A swallowed 403 used to be indistinguishable from an empty result.

    The department bundle degrades on both 403 and 404, so both are recorded.
    Entries are ``"<branch>:<status>"`` and a memo branch is itself
    ``"memo:<field>"``, which is why they must be split with ``rsplit``.
    """
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    for path in ("employees", "requests", "assets"):
        respx.get(f"{ROOT}/{path}").mock(return_value=httpx.Response(status))
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(status)
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(60, resolve_manager=False)
    for branch in (
        "employees",
        "recent_tickets",
        "assets",
        "ticket_count",
        "statistics",
        "memo:comment_department",
    ):
        assert f"{branch}:{status}" in ctx.degraded
    # The bundle still assembles; degradation is reported, not raised.
    assert ctx.department.department_id == 60
    assert ctx.note is None


@pytest.mark.parametrize("status", [403, 404])
@respx.mock
async def test_get_department_context_degrades_on_403_and_404(config, status):
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    # Everything related is forbidden/missing; only get_department succeeds.
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(status, json={"ERROR": {"MESSAGE": "no"}})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(status, json={"ERROR": {"MESSAGE": "no"}})
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(status, json={"ERROR": {"MESSAGE": "no"}})
    )
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(status, json={"ERROR": {"MESSAGE": "no"}})
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(60)
    assert ctx.employees == []
    assert ctx.manager is None
    assert ctx.note is None
    assert ctx.ticket_count == 0
    assert ctx.recent_tickets == []
    assert ctx.ticket_statistics is None
    assert ctx.assets == []


@pytest.mark.parametrize("status", [404, 403])
@respx.mock
async def test_get_department_context_manager_degrades_rest_assembles(config, status):
    # Only the manager lookup fails; every other related part still assembles.
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(
            200, json={"records": [{"DEPARTMENT_ID": 60, "MANAGER_ID": 42}]}
        )
    )
    respx.get(f"{ROOT}/employees/42").mock(
        return_value=httpx.Response(status, json={"ERROR": {"MESSAGE": "no"}})
    )
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": [{"EMPLOYEE_ID": 1}]})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": "note"})
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [{"RFC_NUMBER": "I1"}], "total_record_count": 1}
        )
    )
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(200, json={"records": [{"ASSET_ID": 7}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(60)
    assert ctx.manager is None
    assert ctx.department.department_id == 60
    assert ctx.employees[0].employee_id == 1
    assert ctx.note == "note"
    assert ctx.ticket_count == 1
    assert ctx.assets[0].asset_id == 7


@respx.mock
async def test_get_department_context_trim_flags_skip_related_calls(config):
    # With every trim flag off, the manager/note/assets/statistics calls must
    # never be issued at all — respx raises on any unmocked route, so leaving
    # employees/42, comment_department and assets unmocked proves the trim.
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(
            200, json={"records": [{"DEPARTMENT_ID": 60, "MANAGER_ID": 42}]}
        )
    )
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": [{"EMPLOYEE_ID": 1}]})
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [{"RFC_NUMBER": "I1"}], "total_record_count": 1}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(
            60,
            include_assets=False,
            include_note=False,
            resolve_manager=False,
            include_statistics=False,
        )
    assert ctx.assets == []
    assert ctx.note is None
    assert ctx.manager is None
    assert ctx.ticket_statistics is None
    # The untrimmed parts still assemble normally.
    assert ctx.employees[0].employee_id == 1
    assert ctx.ticket_count == 1


@respx.mock
async def test_get_department_context_rejects_unsafe_department_id(config):
    """department_id feeds ``DEPARTMENT_ID:"<id>"`` search filters for the
    employees/tickets/assets lookups. get_department_context has no fallback
    scan (unlike find_departments), so an unsafe department_id must raise
    rather than silently proceed with a malformed search.

    get_department runs first and is mocked to SUCCEED here, so execution
    actually reaches the search-building line instead of stopping early on a
    404 — otherwise this test would pass for the wrong reason.
    """
    department_id = 'ALPHA",DEPARTMENT_ID:"999'
    respx.get(f"{ROOT}/departments/{department_id}").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    employees_route = respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    requests_route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": [], "total_record_count": 0})
    )
    assets_route = respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    comment_route = respx.get(
        f"{ROOT}/departments/{department_id}/comment_department"
    ).mock(return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": ""}))
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError):
            await client.get_department_context(department_id)
    # The raise must happen before any related lookup, not be swallowed by the
    # try/except that degrades those lookups to empty lists.
    assert employees_route.call_count == 0
    assert requests_route.call_count == 0
    assert assets_route.call_count == 0
    assert comment_route.call_count == 0


@respx.mock
async def test_get_department_context_rejects_blank_department_id(config):
    """A blank department_id must raise too — ``search=None`` reaching
    iter_employees would list every employee, not just this department's.
    """
    department_id = "   "
    respx.get(f"{ROOT}/departments/{department_id}").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    employees_route = respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError, match="department_id is required"):
            await client.get_department_context(department_id)
    assert employees_route.call_count == 0


# --- the escape hatch --------------------------------------------------------


@respx.mock
async def test_send_reaches_an_unwrapped_route_and_returns_raw_json(config):
    # `status` is a reference table this package does not wrap. Nothing is
    # validated into a model and no envelope is unwrapped: the caller owns the
    # shape, which is the point.
    route = respx.get(f"{ROOT}/status").mock(
        return_value=httpx.Response(200, json={"records": [{"STATUS_ID": 8}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        assert await client.send("GET", "status") == {"records": [{"STATUS_ID": 8}]}
    assert route.call_count == 1


@respx.mock
async def test_send_upper_cases_the_method_and_strips_a_leading_slash(config):
    route = respx.get(f"{ROOT}/status").mock(return_value=httpx.Response(200, json={}))
    async with AsyncEasyvistaClient(config) as client:
        await client.send("get", "/status")
    assert route.call_count == 1


@respx.mock
async def test_send_shares_the_error_mapping_and_retry_policy(config):
    # Proves it rides the one transport path rather than a parallel one: 403
    # maps, 590 maps and is NOT retried, 5xx IS retried.
    respx.get(f"{ROOT}/known-errors").mock(return_value=httpx.Response(403))
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaAuthError):
            await client.send("GET", "known-errors")

    rejected = respx.post(f"{ROOT}/problems").mock(
        return_value=httpx.Response(590, json={"error": "nope", "error_code": 2013})
    )
    retried = respx.get(f"{ROOT}/licenses").mock(return_value=httpx.Response(503))
    retrying = EasyvistaConfig(
        server="https://ev.test", account="acme", token="tok", max_retries=2
    )
    async with AsyncEasyvistaClient(retrying) as client:
        with pytest.raises(EasyvistaValidationError):
            await client.send("POST", "problems", json={})
        with pytest.raises(EasyvistaServerError):
            await client.send("GET", "licenses")
    assert rejected.call_count == 1  # 590 is deterministic, never retried
    assert retried.call_count == 3  # 1 attempt + 2 retries


@respx.mock
async def test_send_puts_a_bare_list_body_on_the_wire(config):
    # Pins the RequestSpec.json widening to Any: some unwrapped routes take a
    # bare list, and httpx accepts anything JSON-serialisable.
    route = respx.post(f"{ROOT}/groups").mock(return_value=httpx.Response(200, json={}))
    async with AsyncEasyvistaClient(config) as client:
        await client.send("POST", "groups", json=[{"a": 1}])
    assert json.loads(route.calls.last.request.content) == [{"a": 1}]


@respx.mock
async def test_send_never_reaches_a_foreign_host(config):
    # The credential stays scoped to the configured instance BY CONSTRUCTION:
    # `path` is always joined to api_root, never treated as an absolute URL. So
    # an absolute URL becomes a nonsense path under the instance rather than a
    # request to the host it names -- and the token never leaves the instance.
    foreign = respx.get("https://attacker.test/steal").mock(
        return_value=httpx.Response(200, json={"stolen": True})
    )
    joined = respx.get(
        f"{ROOT}/https://attacker.test/steal",
    ).mock(return_value=httpx.Response(404, json={}))
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError):
            await client.send("GET", "https://attacker.test/steal")
    assert foreign.call_count == 0
    assert joined.call_count == 1


# --- per-call query parameters -----------------------------------------------


@respx.mock
async def test_search_tickets_sends_params_alongside_the_builders_own(config):
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.search_tickets(params={"formatDate": "iso"})
    url = route.calls.last.request.url
    assert url.params["formatDate"] == "iso"
    assert url.params["max_rows"] == "100"


@respx.mock
async def test_a_caller_param_cannot_replace_the_builders_own(config):
    # merge_params layers the spec LAST, so a caller cannot silently change what
    # the method is actually asking for.
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.search_tickets(max_rows=10, params={"max_rows": 5})
    assert route.calls.last.request.url.params["max_rows"] == "10"


@respx.mock
async def test_iter_tickets_still_advances_the_offset_when_params_override_it(config):
    # The pagination hazard: a caller passing offset= must not stall the sweep.
    # The builder's offset wins on every page, so this terminates.
    respx.get(f"{ROOT}/requests").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "records": [{"RFC_NUMBER": "I1"}, {"RFC_NUMBER": "I2"}],
                    "@next": f"{ROOT}/requests?offset=2",
                },
            ),
            httpx.Response(200, json={"records": [{"RFC_NUMBER": "I3"}]}),
        ]
    )
    async with AsyncEasyvistaClient(config) as client:
        seen = [t.rfc_number async for t in client.iter_tickets(params={"offset": 0})]
    assert seen == ["I1", "I2", "I3"]


@respx.mock
async def test_list_actions_keeps_its_rfc_filter_when_a_caller_passes_search(config):
    # ',' is a live combinator in this grammar, so a caller-supplied search that
    # replaced the builder's filter could list another ticket's actions.
    route = respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.list_actions("I1", params={"search": 'RFC_NUMBER:"other"'})
    assert route.calls.last.request.url.params["search"] == 'REQUEST.RFC_NUMBER:"I1"'


@respx.mock
async def test_get_ticket_forwards_a_fields_projection(config):
    """A projection on the item route, for when one column poisons the record.

    A value the read model refuses fails the entire ``Request``, and without
    this there was no way to read the rest of the ticket. Note the item route
    may ignore ``fields`` -- the verified instance's own OpenAPI declares it on
    ``GET /requests`` but not on ``GET /requests/{rfc_number}``.
    """
    route = respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"records": [{"RFC_NUMBER": "I1"}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.get_ticket("I1", fields=["RFC_NUMBER", "TITLE"])
    assert route.calls.last.request.url.params["fields"] == "RFC_NUMBER,TITLE"


@respx.mock
async def test_a_configured_datetime_format_is_honoured_end_to_end(config):
    """The only test that walks the whole thread: config field to model_validate.

    The read models refuse a timestamp they cannot parse rather than guessing
    an instant, and a search validates a whole page in one comprehension -- so
    on a deployment whose format differs, one column fails every record on the
    page. ``datetime_input_formats`` is the way through that is not a fork.

    Both halves matter. The default config must still refuse the payload (the
    guard is not softened), and the configured one must accept it (the context
    actually reaches ``model_validate`` through 26 builder signatures).
    """
    payload = {"records": [{"RFC_NUMBER": "I1", "LAST_UPDATE": "17/08/2026 15:40:00"}]}
    respx.get(f"{ROOT}/requests").mock(return_value=httpx.Response(200, json=payload))

    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(
            pydantic.ValidationError, match="not an EasyVista timestamp"
        ):
            await client.search_tickets()

    tolerant = dataclasses.replace(
        config, datetime_input_formats=("%d/%m/%Y %H:%M:%S",)
    )
    async with AsyncEasyvistaClient(tolerant) as client:
        result = await client.search_tickets()
    assert result.records[0].last_update is not None
    assert result.records[0].last_update.year == 2026


# --- instance discovery ------------------------------------------------------


@respx.mock
async def test_get_api_spec_accepts_a_201_response(config):
    """The regression guard for the ``== 200`` trap.

    A GET to this route answers **201**, not 200 (measured 2026-08-27 on one
    instance). This client's transport gates on ``is_success``, so any 2xx
    works -- but code written beside it that checks ``status_code == 200``
    skips the document in silence and concludes the instance publishes no spec.
    Asserting on 201 specifically is the whole point; a 200 here would prove
    nothing.
    """
    respx.get(f"{ROOT}/swagger").mock(
        return_value=httpx.Response(
            201, json={"info": {"description": "EV REST API - 2025.3"}, "paths": {}}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        document = await client.get_api_spec()
    assert document["info"]["description"] == "EV REST API - 2025.3"


@respx.mock
async def test_get_api_spec_honours_a_custom_path(config):
    """The route is tier 4 -- measured on one instance and NOT declared in that
    instance's own paths -- so a deployment publishing elsewhere needs a way
    through that is not a fork."""
    route = respx.get(f"{ROOT}/openapi.json").mock(
        return_value=httpx.Response(200, json={"paths": {}})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.get_api_spec(path="openapi.json")
    assert route.call_count == 1


@respx.mock
async def test_list_reference_table_lets_a_403_propagate(config):
    """A denial must not look like an empty table.

    An empty reference table is a legitimate answer on a lightly configured
    instance. Collapsing a 403 into ``[]`` would make "you may not read this"
    indistinguishable from "there is nothing here" -- and a caller building a
    status map from ``[]`` concludes the instance has no statuses and reaches
    for a hardcoded constant. ``describe_instance`` is the swallowing layer.
    """
    respx.get(f"{ROOT}/catalog-requests").mock(return_value=httpx.Response(403))
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaAuthError):
            await client.list_reference_table("catalog-requests")


@respx.mock
async def test_list_reference_table_returns_a_search_result_with_counts(config):
    """A SearchResult, not a bare list, so truncation is detectable."""
    respx.get(f"{ROOT}/urgency").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"URGENCY_ID": 1, "URGENCY_EN": "Low"}],
                "record_count": "1",
                "total_record_count": "7",
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        page = await client.list_reference_table("urgency")
    assert page.record_count == 1
    assert page.total_record_count == 7
    assert page.records[0].model_dump(by_alias=True)["URGENCY_EN"] == "Low"


@respx.mock
async def test_discover_status_populates_the_guid_from_a_ticket_sample(config):
    """The STATUS_GUID recipe, asserted end to end.

    A STATUS_GUID is not searchable and no reference read returns one, but
    every ticket's nested STATUS object carries it. The GUID is what
    ``set_status`` and ``close_ticket`` address a status by -- a STATUS_ID will
    not work there -- so this is usually the value the caller came for.
    """
    respx.get(f"{ROOT}/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {"STATUS_ID": 8, "STATUS_FR": "Cloture"},
                    {"STATUS_ID": 12, "STATUS_FR": "En cours"},
                ]
            },
        )
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {
                        "RFC_NUMBER": "I1",
                        "STATUS": {
                            "STATUS_ID": "8",
                            "STATUS_GUID": "{ABC}",
                            "STATUS_FR": "Cloture",
                        },
                    }
                ]
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.discover("STATUS", sample_size=5)
    by_id = {r.id: r for r in found}
    assert by_id["8"].guid == "{ABC}"
    # A status present in the table but held by no sampled ticket keeps
    # guid=None: the sample cannot reach it, and inventing one would hand back
    # a GUID that addresses nothing.
    assert by_id["12"].guid is None


@respx.mock
async def test_discover_a_routeless_name_never_calls_a_reference_route(config):
    """IMPACT has no route in the spec at all, so no request is wasted on one."""
    impact_route = respx.get(f"{ROOT}/impact").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {"RFC_NUMBER": "I1", "IMPACT_ID": "17"},
                    {"RFC_NUMBER": "I2", "IMPACT_ID": "17"},
                    {"RFC_NUMBER": "I3", "IMPACT_ID": "21"},
                ]
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.discover("IMPACT", sample_size=10)
    assert impact_route.call_count == 0
    assert [(r.id, r.count) for r in found] == [("17", 2), ("21", 1)]
    assert all(r.source == "sample" for r in found)


@respx.mock
async def test_discover_strategy_reference_lets_a_403_raise(config):
    respx.get(f"{ROOT}/status").mock(return_value=httpx.Response(403))
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaAuthError):
            await client.discover("STATUS", strategy="reference")


@respx.mock
async def test_discover_auto_falls_back_to_the_sample_on_a_denied_route(config):
    respx.get(f"{ROOT}/status").mock(return_value=httpx.Response(403))
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {
                        "RFC_NUMBER": "I1",
                        "STATUS": {"STATUS_ID": "8", "STATUS_FR": "Cloture"},
                    }
                ]
            },
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.discover("STATUS", sample_size=5)
    assert [(r.id, r.source) for r in found] == [("8", "sample")]


async def test_discover_strategy_reference_refuses_a_routeless_name(config):
    """Rather than quietly sampling, which would answer a different question."""
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError, match="no reference route"):
            await client.discover("IMPACT", strategy="reference")


async def test_discover_refuses_an_unknown_strategy(config):
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError, match="strategy="):
            await client.discover("STATUS", strategy="guess")


@respx.mock
async def test_describe_instance_names_every_gap_and_still_returns_a_profile(config):
    """No part can fail the whole.

    ``/catalog-requests`` is denied here and everything else succeeds: the
    profile still holds the other names, and the gap is named rather than
    silently empty.
    """
    respx.get(f"{ROOT}/swagger").mock(
        return_value=httpx.Response(
            201,
            json={
                "info": {"description": "EV REST API - 2025.3"},
                "paths": {"/requests": {}, "/actions": {}},
            },
        )
    )
    respx.get(f"{ROOT}/catalog-requests").mock(return_value=httpx.Response(403))
    for table in ("status", "urgency", "locations", "departments", "slas", "groups"):
        respx.get(f"{ROOT}/{table}").mock(
            return_value=httpx.Response(200, json={"records": [{"NAME_EN": "x"}]})
        )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [{"RFC_NUMBER": "I1", "IMPACT_ID": "17"}]}
        )
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(
            200, json={"records": [{"ACTION_ID": 1, "ACTION_TYPE_ID": 94}]}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        profile = await client.describe_instance(
            sample_size=5, action_sample_tickets=1
        )
    assert profile.version == "EV REST API - 2025.3"
    assert "/requests" in profile.spec_paths
    assert profile.unavailable["CATALOG_REQUEST"].startswith("denied")
    assert profile.references["STATUS"]
    assert profile.references["IMPACT"][0].id == "17"
    # The four routeless names say so, rather than looking like empty tables.
    for routeless in ("IMPACT", "SEVERITY", "ORIGIN", "ACTION_TYPE"):
        assert profile.unavailable[routeless].startswith("no-route")


@respx.mock
async def test_describe_instance_records_a_truncated_table(config):
    """The rows present are real; they are just not all of them."""
    respx.get(f"{ROOT}/swagger").mock(
        return_value=httpx.Response(201, json={"info": {}, "paths": {}})
    )
    respx.get(f"{ROOT}/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"STATUS_ID": 8, "STATUS_FR": "Cloture"}],
                "record_count": 1,
                "total_record_count": 40,
            },
        )
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        profile = await client.describe_instance(names=["STATUS"], sample_size=1)
    assert profile.unavailable["STATUS"].startswith("truncated")
    assert profile.references["STATUS"]  # and the rows still came back


@respx.mock
async def test_describe_instance_returns_a_profile_when_everything_is_denied(config):
    """A total outage looks like a bare instance EXCEPT that every gap is named.

    Which is exactly why the docstring tells the reader to check
    ``.unavailable`` before concluding an instance has no statuses.
    """
    respx.route(host="ev.test").mock(return_value=httpx.Response(403))
    async with AsyncEasyvistaClient(config) as client:
        profile = await client.describe_instance(
            names=["STATUS", "IMPACT"], sample_size=1
        )
    assert profile.spec_paths == ()
    assert profile.unavailable["spec"].startswith("denied")
    assert profile.references["STATUS"] == []
    assert profile.references["IMPACT"] == []


@respx.mock
async def test_end_action_forwards_every_keyword_to_the_body(config):
    """Pin the kwarg forwarding, ``start_date`` above all.

    A dropped ``start_date`` is invisible in the response -- the server simply
    derives one, and the derived one is early by the instance's UTC offset. So
    this asserts the wire body, not the return value.
    """
    route = respx.put(f"{ROOT}/actions/I1").mock(
        return_value=httpx.Response(200, json={"HREF": f"{ROOT}/requests/I1"})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.end_action(
            "I1",
            action_id=42,
            start_date="01/09/2026 17:00:00",
            end_date="01/09/2026 17:15:00",
            elapsed_time=15,
            doneby_mail="tech@example.invalid",
        )
    assert json.loads(route.calls.last.request.content) == {
        "end_action": {
            "action_id": 42,
            "start_date": "01/09/2026 17:00:00",
            "end_date": "01/09/2026 17:15:00",
            "elapsed_time": 15,
            "doneby_mail": "tech@example.invalid",
        }
    }


@respx.mock
async def test_end_action_addresses_the_ticket_not_the_action(config):
    """``actions/{action_id}`` answers 404 for this verb; the RFC is the path."""
    route = respx.put(f"{ROOT}/actions/I1").mock(
        return_value=httpx.Response(200, json={"HREF": f"{ROOT}/requests/I1"})
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.end_action("I1", action_id=42)
    assert route.calls.last.request.url.path.endswith("/actions/I1")


async def test_end_action_refuses_a_missing_action_id_before_any_request(config):
    """No socket is opened: the refusal is local, so respx is not even needed."""
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(ValueError, match="end_all"):
            await client.end_action("I1", end_date="01/09/2026 17:00:00")
