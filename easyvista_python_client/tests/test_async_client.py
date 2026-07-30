import asyncio
import json

import httpx
import pytest
import respx

from easyvista_python_client._async.client import _ACTION_FANOUT, AsyncEasyvistaClient
from easyvista_python_client.exceptions import EasyvistaError, EasyvistaNotFound
from easyvista_python_client.models.action import PostAction
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
from easyvista_python_client.models.request import PostRequest

ROOT = "https://ev.test/api/v1/acme"


@respx.mock
async def test_async_create_and_get_ticket(config):
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
async def test_async_create_tickets_creates_each_ticket(config):
    # Fan out to one POST per ticket (EasyVista creates only the first item of
    # a multi-item body).
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
async def test_async_search_and_actions(config):
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
    respx.post(f"{ROOT}/requests/I1/actions").mock(
        return_value=httpx.Response(200, json={"records": [{"ACTION_ID": 7}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        result = await client.search_tickets(max_rows=5)
        action = await client.create_action("I1", PostAction(description="x"))
    assert result.records[0].rfc_number == "I1"
    assert action.action_id == 7


@respx.mock
async def test_async_assets_and_documents(config):
    respx.post(f"{ROOT}/assets").mock(
        return_value=httpx.Response(201, json={"HREF": f"{ROOT}/assets/9504"})
    )
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"ASSET_TAG": "T1"}],
                "record_count": 1,
                "total_record_count": 1,
            },
        )
    )
    respx.get(f"{ROOT}/assets/9504").mock(
        return_value=httpx.Response(200, json={"ASSET_TAG": "T1"})
    )
    respx.post(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(201, json={"HREF": f"{ROOT}/requests/I1"})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"records": [{"HREF": "u1"}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        created = await client.create_asset(PostAsset(catalog_id=1, asset_tag="T1"))
        fetched = await client.get_asset("9504")
        result = await client.search_assets(search="ASSET_TAG~T")
        doc = await client.add_document("I1", filename="a.txt", content=b"hi")
        listed = await client.list_documents("I1")
    assert created.href.endswith("/assets/9504")
    assert fetched.asset_tag == "T1"
    assert result.records[0].asset_tag == "T1"
    assert doc.href.endswith("/requests/I1")
    assert listed[0].href == "u1"


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
async def test_async_iter_tickets_follows_pages(config):
    respx.get(f"{ROOT}/requests").mock(side_effect=_paged_tickets_responder)
    async with AsyncEasyvistaClient(config) as client:
        rfcs = [t.rfc_number async for t in client.iter_tickets(page_size=2)]
    assert rfcs == ["I1", "I2", "I3"]


@respx.mock
async def test_async_iter_assets_follows_pages(config):
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
async def test_async_get_ticket_context_assembles_bundle(config):
    from easyvista_python_client import TicketContext

    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1", "TITLE": "T"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "d"})
    )
    respx.get(f"{ROOT}/requests/I1/comment").mock(
        return_value=httpx.Response(200, json={"COMMENT": "c"})
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
    assert ctx.description == "d"
    assert ctx.comment == "c"


@respx.mock
async def test_async_get_ticket_context_degrades_on_missing_subresources(config):
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


@respx.mock
async def test_async_count_tickets_returns_total_record_count(config):
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
    assert total == 42
    assert route.call_count == 1
    assert route.calls.last.request.url.params["max_rows"] == "1"
    assert route.calls.last.request.url.params["search"] == 'STATUS_ID:"3"'


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
async def test_async_ticket_statistics_aggregates_over_iter_tickets(config):
    from easyvista_python_client import TicketStatistics

    respx.get(f"{ROOT}/requests").mock(side_effect=_stats_responder)
    async with AsyncEasyvistaClient(config) as client:
        stats = await client.ticket_statistics(dimensions=["STATUS"])
    assert isinstance(stats, TicketStatistics)
    assert stats.total == 3
    assert stats.breakdowns["STATUS"] == {"Open": 2, "Closed": 1}


@respx.mock
async def test_async_ticket_statistics_respects_max_records(config):
    respx.get(f"{ROOT}/requests").mock(side_effect=_stats_responder)
    async with AsyncEasyvistaClient(config) as client:
        stats = await client.ticket_statistics(dimensions=["STATUS"], max_records=1)
    assert stats.total == 1  # capped before the second page


@respx.mock
async def test_async_ticket_statistics_requests_field_projection(config):
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        await client.ticket_statistics(dimensions=["URGENCY"])
    fields = route.calls.last.request.url.params["fields"]
    assert "URGENCY_ID" in fields and "RFC_NUMBER" in fields


@respx.mock
async def test_resolve_memo_async(config):
    respx.get(f"{ROOT}/requests/I1/comment").mock(
        return_value=httpx.Response(200, json={"COMMENT": "note", "PARENT_HREF": "x"})
    )
    async with AsyncEasyvistaClient(config) as client:
        assert await client.resolve_memo("requests/I1/comment") == "note"


@respx.mock
async def test_get_department_async(config):
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": "hi"})
    )
    async with AsyncEasyvistaClient(config) as client:
        dept = await client.get_department(60)
        note = await client.get_department_comment(60)
    assert isinstance(dept, Department)
    assert note == "hi"


@respx.mock
async def test_find_departments_async_fuzzy(config):
    respx.get(f"{ROOT}/departments").mock(
        side_effect=[
            httpx.Response(200, json={"records": [], "total_record_count": 0}),
            httpx.Response(
                200,
                json={"records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_FR": "ACME CORP"}]},
            ),
        ]
    )
    async with AsyncEasyvistaClient(config) as client:
        found = await client.find_departments("acmecorp")
    assert [d.department_id for d in found] == [60]


@respx.mock
async def test_find_departments_empty_needle_returns_empty_not_everything_async(config):
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
async def test_get_employee_async(config):
    respx.get(f"{ROOT}/employees/6087").mock(
        return_value=httpx.Response(
            200, json={"records": [{"EMPLOYEE_ID": 6087, "LAST_NAME": "Doe"}]}
        )
    )
    async with AsyncEasyvistaClient(config) as client:
        emp = await client.get_employee(6087)
    assert isinstance(emp, Employee)
    assert emp.last_name == "Doe"


@respx.mock
async def test_async_iter_employees_follows_pages(config):
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
async def test_async_iter_employees_respects_max_records(config):
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
async def test_update_employee_async(config):
    respx.put(f"{ROOT}/employees/9001").mock(
        return_value=httpx.Response(200, json={"records": [{"EMPLOYEE_ID": 9001}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        emp = await client.update_employee(9001, EmployeeUpdate(phone_number="0102"))
    assert emp.employee_id == 9001


@respx.mock
async def test_create_department_and_employee_async(config):
    # Async twin of test_create_department_and_employee: envelope-wrapped POST
    # bodies for create, a bare payload for the PUT update.
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
    assert json.loads(dep_route.calls.last.request.content) == {
        "departments": [{"department_code": "NEW"}]
    }
    assert json.loads(emp_route.calls.last.request.content) == {
        "employees": [{"last_name": "Doe"}]
    }


@respx.mock
async def test_get_department_context_async(config):
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    respx.get(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": ""})
    )
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": [], "total_record_count": 0})
    )
    respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        ctx = await client.get_department_context(60, include_statistics=False)
    assert ctx.department.department_id == 60
    assert ctx.note == ""
    assert ctx.ticket_statistics is None


@respx.mock
async def test_get_department_context_rejects_unsafe_department_id(config):
    """Async twin of the sync rejection test in test_client.py.

    get_department_context has no fallback scan, so an unsafe department_id
    must raise rather than silently proceed with a malformed search.
    get_department is mocked to SUCCEED so execution actually reaches the
    search-building line instead of stopping early on a 404.
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
    assert employees_route.call_count == 0
    assert requests_route.call_count == 0
    assert assets_route.call_count == 0
    assert comment_route.call_count == 0


@respx.mock
async def test_get_department_context_rejects_blank_department_id(config):
    """Async twin: a blank department_id must raise too — ``search=None``
    reaching iter_employees would list every employee.
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


@respx.mock
async def test_find_departments_rejects_comma_injection(config):
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
    assert found == []
    for call in route.calls:
        assert '"' not in (call.request.url.params.get("search") or "")


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


async def test_download_document_refuses_a_foreign_download_url(config):
    doc = Document.model_validate({"DDL_HREF": "https://attacker.test/dl/7"})
    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError, match="outside the configured instance"):
            await client.download_document(doc)


@respx.mock
async def test_get_action_fetches_the_item_level_record(config):
    respx.get(f"{ROOT}/actions/52990").mock(
        return_value=httpx.Response(200, json={"ACTION_ID": 52990})
    )
    async with AsyncEasyvistaClient(config) as client:
        action = await client.get_action(52990)
    assert action.action_id == 52990


@respx.mock
async def test_ticket_context_resolves_action_bodies(config):
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
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
        return_value=httpx.Response(200, json={"DESCRIPTION": "the note"})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    async with AsyncEasyvistaClient(config) as client:
        context = await client.get_ticket_context("I1")
    assert context.actions[0].description == "the note"


@respx.mock
async def test_async_ticket_context_can_skip_resolving_action_bodies(config):
    # Opt-out parity with the sync client: resolving costs two extra requests
    # per action, and a ticket on this instance carries ~11 workflow-generated
    # actions.
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
async def test_async_ticket_context_tolerates_an_unreadable_action(config):
    # Async twin of the sync 403 degrade. The unreadable action stays in the
    # bundle unresolved -- a profile restriction must never silently shorten a
    # ticket's history -- and its readable neighbour still resolves.
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
async def test_async_ticket_context_tolerates_a_missing_action(config):
    # The 404 arm of the same except clause: an action listed but gone by the
    # time we fetch it degrades exactly like a 403, and keeps its slot.
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
async def test_async_ticket_context_keeps_an_action_that_has_no_id(config):
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


# --- concurrency ------------------------------------------------------------
#
# The async client used to be the sync client with `await` inserted: it issued
# every request serially and so was no faster than the sync one (measured
# against a live instance on a 19-action ticket: 14.65s async vs 13.44s sync).
# These tests pin that the independent requests now actually overlap.
#
# Asserting on results alone cannot do that -- the results are identical either
# way, which is the whole point. So each test measures PEAK OVERLAP through a
# mock that holds the connection open, and
# `test_inflight_tracker_reports_one_for_sequential_code` is the negative
# control proving the tracker can tell serial from concurrent at all.


class _InFlight:
    """Counts mocked requests that are open simultaneously.

    ``peak`` is the largest number that overlapped. A serial implementation can
    never exceed 1, so this is direct evidence of concurrency rather than a
    proxy for it.
    """

    def __init__(self) -> None:
        self.current = 0
        self.peak = 0

    def respond(self, payload, delay=0.02, status=200):
        async def _handler(request):
            self.current += 1
            self.peak = max(self.peak, self.current)
            try:
                await asyncio.sleep(delay)
            finally:
                self.current -= 1
            return httpx.Response(status, json=payload)

        return _handler


@respx.mock
async def test_inflight_tracker_reports_one_for_sequential_code(config):
    """Negative control. Without it the peaks below prove nothing.

    ``create_tickets`` is deliberately sequential (writes: EasyVista assigns the
    RFC server-side, so a mid-batch failure must leave a knowable prefix). The
    same tracker must therefore report a peak of exactly 1 against it. If this
    ever reports more, the tracker is broken and every concurrency assertion in
    this file is worthless.
    """
    flight = _InFlight()
    respx.post(f"{ROOT}/requests").mock(
        side_effect=flight.respond({"records": [{"RFC_NUMBER": "I1"}]})
    )
    async with AsyncEasyvistaClient(config) as client:
        await asyncio.wait_for(
            client.create_tickets([PostRequest(catalog_code="C")] * 4), timeout=10
        )
    assert flight.peak == 1


@respx.mock
async def test_ticket_context_issues_its_subresources_concurrently(config):
    """The four independent sub-resource requests overlap; the ticket does not.

    ``get_ticket`` is wave 0 on purpose -- it is the only call with no fallback,
    so a wrong RFC must cost one request rather than five. A peak of exactly 4
    proves both halves at once: the four overlapped, and the ticket GET did not
    join them.
    """
    flight = _InFlight()
    respx.get(f"{ROOT}/requests/I1").mock(
        side_effect=flight.respond({"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(
        side_effect=flight.respond({"DESCRIPTION": "d"})
    )
    respx.get(f"{ROOT}/requests/I1/comment").mock(
        side_effect=flight.respond({"COMMENT": "c"})
    )
    respx.get(f"{ROOT}/actions").mock(side_effect=flight.respond({"actions": []}))
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        side_effect=flight.respond({"Documents": []})
    )

    async with AsyncEasyvistaClient(config) as client:
        context = await asyncio.wait_for(client.get_ticket_context("I1"), timeout=10)

    assert context.description == "d"
    assert context.comment == "c"
    assert flight.peak == 4


@respx.mock
async def test_action_bodies_resolve_concurrently_up_to_the_fanout_bound(config):
    """25 action bodies resolve concurrently, but never more than the bound.

    ``peak == _ACTION_FANOUT`` asserts both properties in one line: they are
    concurrent (peak > 1) and they are bounded (peak never exceeds the ceiling).
    A ticket's action count is set by the server, so an unbounded fan-out would
    present arbitrarily many simultaneous requests to a customer instance.
    """
    flight = _InFlight()
    listed = [{"ACTION_ID": i} for i in range(1, 26)]
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": listed})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )
    for i in range(1, 26):
        # A plain-string DESCRIPTION resolves without a second memo request, so
        # the tracker counts exactly one request per action.
        respx.get(f"{ROOT}/actions/{i}").mock(
            side_effect=flight.respond({"ACTION_ID": i, "DESCRIPTION": "note"})
        )

    async with AsyncEasyvistaClient(config) as client:
        context = await asyncio.wait_for(client.get_ticket_context("I1"), timeout=30)

    assert len(context.actions) == 25
    assert flight.peak == _ACTION_FANOUT


@respx.mock
async def test_resolved_actions_keep_list_order_despite_completion_order(config):
    """Out-of-order completion must not reorder the history.

    Action 7 is slow and action 8 is instant, so they complete in reverse. The
    bundle must still read [7, 8] -- ``settle`` returns results in source
    order. The other tests here mock with ``return_value=``, which is
    order-agnostic and would stay green under a shuffle.
    """
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
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )

    async def _slow(request):
        await asyncio.sleep(0.10)
        return httpx.Response(200, json={"ACTION_ID": 7, "DESCRIPTION": "seven"})

    respx.get(f"{ROOT}/actions/7").mock(side_effect=_slow)
    respx.get(f"{ROOT}/actions/8").mock(
        return_value=httpx.Response(200, json={"ACTION_ID": 8, "DESCRIPTION": "eight"})
    )

    async with AsyncEasyvistaClient(config) as client:
        context = await asyncio.wait_for(client.get_ticket_context("I1"), timeout=10)

    assert [a.action_id for a in context.actions] == [7, 8]
    assert [a.description for a in context.actions] == ["seven", "eight"]


@respx.mock
async def test_the_source_ordered_failure_wins_not_the_fastest(config):
    """Which exception surfaces must not depend on server timing.

    Two branches fail hard. The description memo is first in source order but
    answers slowly; documents is last but fails instantly. The caller must see
    the description failure -- the one the old sequential code would have hit.
    A bare ``gather`` (no ``return_exceptions=True``) raises the documents one
    instead, so this is the permanent lock against that simplification.
    """
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )

    async def _slow_failure(request):
        await asyncio.sleep(0.10)
        return httpx.Response(500, json={"error": "DESCRIPTION_BRANCH_FAILED"})

    respx.get(f"{ROOT}/requests/I1/description").mock(side_effect=_slow_failure)
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": []})
    )
    documents = respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(500, json={"error": "DOCUMENTS_BRANCH_FAILED"})
    )

    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError) as excinfo:
            await asyncio.wait_for(client.get_ticket_context("I1"), timeout=10)

    message = str(excinfo.value)
    assert "DESCRIPTION_BRANCH_FAILED" in message
    assert "DOCUMENTS_BRANCH_FAILED" not in message
    # ...and the faster failure was still awaited rather than orphaned.
    assert documents.call_count == 1


@respx.mock
async def test_no_sibling_request_outlives_a_failed_bundle(config):
    """A failing bundle settles every sibling before it raises.

    A bare ``gather`` propagates the first exception with its siblings still
    running; those orphans can be in flight when ``__aexit__`` closes the
    client. Here the slow branch is still open when the fast one fails, so if it
    were orphaned its handler would not have finished by the time we assert.
    """
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(500, json={"error": "fail fast"})
    )

    slow_finished = []

    async def _slow(request):
        await asyncio.sleep(0.15)
        slow_finished.append(True)
        return httpx.Response(200, json={"Documents": []})

    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"actions": []})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(side_effect=_slow)

    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError):
            await asyncio.wait_for(client.get_ticket_context("I1"), timeout=10)
        assert slow_finished == [True]


@respx.mock
async def test_a_404_on_the_action_list_still_fails_the_bundle(config):
    """The 403-only asymmetry survives the rewrite.

    ``list_actions`` and ``list_documents`` catch ``EasyvistaAuthError`` ONLY,
    so a 404 there propagates and fails the whole bundle, while the memos
    degrade on both 403 and 404. Tidying the wrappers into one shared handler
    would widen this silently, and every other test in this file would stay
    green.
    """
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    respx.get(f"{ROOT}/requests/I1/description").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/comment").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/actions").mock(return_value=httpx.Response(404))
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"Documents": []})
    )

    async with AsyncEasyvistaClient(config) as client:
        with pytest.raises(EasyvistaNotFound):
            await asyncio.wait_for(client.get_ticket_context("I1"), timeout=10)


@respx.mock
async def test_department_context_issues_its_branches_concurrently(config):
    """The seven independent department branches overlap.

    ``get_department`` stays in wave 0 because the manager lookup needs its
    ``MANAGER_ID``. The tracker covers only the branch routes, so the peak is
    evidence the branches overlap each other rather than that something
    overlapped the department GET.
    """
    flight = _InFlight()
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"DEPARTMENT_ID": 60, "MANAGER_ID": 9})
    )
    respx.get(f"{ROOT}/employees/9").mock(
        side_effect=flight.respond({"EMPLOYEE_ID": 9})
    )
    respx.get(f"{ROOT}/employees").mock(
        side_effect=flight.respond({"records": [], "TOTAL_RECORD_COUNT": 0})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        side_effect=flight.respond({"COMMENT_DEPARTMENT": "note"})
    )
    respx.get(f"{ROOT}/requests").mock(
        side_effect=flight.respond({"records": [], "TOTAL_RECORD_COUNT": 0})
    )
    respx.get(f"{ROOT}/assets").mock(
        side_effect=flight.respond({"records": [], "TOTAL_RECORD_COUNT": 0})
    )

    async with AsyncEasyvistaClient(config) as client:
        context = await asyncio.wait_for(client.get_department_context(60), timeout=30)

    assert context.department.department_id == 60
    assert context.note == "note"
    # employees, manager, note, ticket_count, recent, statistics, assets
    assert flight.peak == 7
