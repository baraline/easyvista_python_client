import json

import httpx
import pytest
import respx

from easyvista_python_client.client import EasyvistaClient
from easyvista_python_client.directory import DepartmentContext
from easyvista_python_client.exceptions import EasyvistaError
from easyvista_python_client.models.action import PostAction
from easyvista_python_client.models.asset import PostAsset
from easyvista_python_client.models.department import (
    Department,
    DepartmentUpdate,
    PostDepartment,
)
from easyvista_python_client.models.document import Document
from easyvista_python_client.models.employee import Employee, PostEmployee
from easyvista_python_client.models.request import PostRequest, RequestUpdate

ROOT = "https://ev.test/api/v1/acme"


@respx.mock
def test_create_and_get_ticket(config):
    respx.post(f"{ROOT}/requests").mock(
        return_value=httpx.Response(200, json={"records": [{"RFC_NUMBER": "I1"}]})
    )
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1", "STATUS_ID": 2})
    )
    with EasyvistaClient(config) as client:
        created = client.create_ticket(PostRequest(catalog_code="C"))
        fetched = client.get_ticket("I1")
    assert created.rfc_number == "I1"
    assert fetched.status_id == 2


@respx.mock
def test_create_tickets_creates_each_ticket(config):
    # EasyVista's POST /requests creates only the first item of a multi-item
    # body, so create_tickets must fan out to one POST per ticket.
    route = respx.post(f"{ROOT}/requests").mock(
        side_effect=[
            httpx.Response(200, json={"HREF": f"{ROOT}/requests/I1"}),
            httpx.Response(200, json={"HREF": f"{ROOT}/requests/I2"}),
        ]
    )
    with EasyvistaClient(config) as client:
        created = client.create_tickets(
            [PostRequest(catalog_code="A"), PostRequest(catalog_code="B")]
        )
    assert route.call_count == 2
    assert [t.rfc_number for t in created] == ["I1", "I2"]


@respx.mock
def test_search_tickets(config):
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
    with EasyvistaClient(config) as client:
        result = client.search_tickets(search='STATUS_ID:"3"', max_rows=10)
    assert result.total_record_count == 3
    assert result.records[0].rfc_number == "I1"


@respx.mock
def test_search_tickets_applies_default_max_rows(config):
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )
    )
    with EasyvistaClient(config) as client:
        client.search_tickets()
    assert route.calls.last.request.url.params["max_rows"] == "100"


@respx.mock
def test_update_and_close_ticket(config):
    respx.put(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"records": [{"RFC_NUMBER": "I1"}]})
    )
    with EasyvistaClient(config) as client:
        client.update_ticket("I1", RequestUpdate(status_id=4))
        client.close_ticket("I1", comment="resolved")


@respx.mock
def test_create_and_list_actions(config):
    respx.post(f"{ROOT}/requests/I1/actions").mock(
        return_value=httpx.Response(200, json={"records": [{"ACTION_ID": 5}]})
    )
    respx.get(f"{ROOT}/actions").mock(
        return_value=httpx.Response(200, json={"records": [{"ACTION_ID": 5}]})
    )
    with EasyvistaClient(config) as client:
        action = client.create_action("I1", PostAction(description="hi"))
        listed = client.list_actions("I1")
    assert action.action_id == 5
    assert listed[0].action_id == 5


@respx.mock
def test_from_env_constructs_working_client(monkeypatch):
    monkeypatch.setenv("EASYVISTA_URL", "https://ev.test")
    monkeypatch.setenv("EASYVISTA_ACCOUNT", "acme")
    monkeypatch.setenv("EASYVISTA_TOKEN", "tok")
    respx.get(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(200, json={"RFC_NUMBER": "I1"})
    )
    with EasyvistaClient.from_env() as client:
        assert client.get_ticket("I1").rfc_number == "I1"


@respx.mock
def test_create_and_get_asset(config):
    respx.post(f"{ROOT}/assets").mock(
        return_value=httpx.Response(201, json={"HREF": f"{ROOT}/assets/9504"})
    )
    respx.get(f"{ROOT}/assets/9504").mock(
        return_value=httpx.Response(200, json={"ASSET_TAG": "T1"})
    )
    with EasyvistaClient(config) as client:
        created = client.create_asset(PostAsset(catalog_id=3153, asset_tag="T1"))
        fetched = client.get_asset("9504")
    assert created.href.endswith("/assets/9504")
    assert fetched.asset_tag == "T1"


@respx.mock
def test_search_assets(config):
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
    with EasyvistaClient(config) as client:
        result = client.search_assets(search="ASSET_TAG~T")
    assert result.total_record_count == 2
    assert result.records[0].asset_tag == "T1"


@respx.mock
def test_search_assets_applies_default_max_rows(config):
    route = respx.get(f"{ROOT}/assets").mock(
        return_value=httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )
    )
    with EasyvistaClient(config) as client:
        client.search_assets()
    assert route.calls.last.request.url.params["max_rows"] == "100"


@respx.mock
def test_add_and_list_documents(config):
    add_route = respx.post(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(201, json={"HREF": f"{ROOT}/requests/I1"})
    )
    respx.get(f"{ROOT}/requests/I1/documents").mock(
        return_value=httpx.Response(200, json={"records": [{"HREF": "u1"}]})
    )
    with EasyvistaClient(config) as client:
        doc = client.add_document("I1", filename="a.txt", content=b"hi")
        listed = client.list_documents("I1")
    assert doc.href.endswith("/requests/I1")
    assert listed[0].href == "u1"
    import json as _json

    body = _json.loads(add_route.calls.last.request.content)
    assert body["documents"][0]["filename"] == "a.txt"


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
def test_iter_tickets_follows_pages(config):
    respx.get(f"{ROOT}/requests").mock(side_effect=_paged_tickets_responder)
    with EasyvistaClient(config) as client:
        rfcs = [t.rfc_number for t in client.iter_tickets(page_size=2)]
    assert rfcs == ["I1", "I2", "I3"]


@respx.mock
def test_iter_tickets_respects_max_records(config):
    route = respx.get(f"{ROOT}/requests").mock(side_effect=_paged_tickets_responder)
    with EasyvistaClient(config) as client:
        rfcs = [t.rfc_number for t in client.iter_tickets(page_size=2, max_records=1)]
    assert rfcs == ["I1"]
    # Stops after the first page once the cap is hit (no second request).
    assert route.calls.last.request.url.params["offset"] == "0"


@respx.mock
def test_iter_tickets_stops_on_empty_page(config):
    respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )
    )
    with EasyvistaClient(config) as client:
        assert list(client.iter_tickets(page_size=2)) == []


@respx.mock
def test_iter_assets_follows_pages(config):
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
    with EasyvistaClient(config) as client:
        tags = [a.asset_tag for a in client.iter_assets(page_size=2)]
    assert tags == ["A1", "A2", "A3"]


@respx.mock
def test_get_ticket_context_assembles_bundle(config):
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

    with EasyvistaClient(config) as client:
        ctx = client.get_ticket_context("I1")

    assert isinstance(ctx, TicketContext)
    assert ctx.ticket.rfc_number == "I1"
    assert ctx.description == "<p>hi</p>"
    assert ctx.comment == "note"
    assert ctx.to_markdown().startswith("# Ticket")
    assert "/api/" not in ctx.to_markdown()


@respx.mock
def test_get_ticket_context_degrades_on_missing_subresources(config):
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

    with EasyvistaClient(config) as client:
        ctx = client.get_ticket_context("I1")

    assert ctx.description is None
    assert ctx.comment is None
    assert ctx.actions == []
    assert ctx.documents == []


@respx.mock
def test_count_tickets_returns_total_record_count(config):
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
    with EasyvistaClient(config) as client:
        total = client.count_tickets(search='STATUS_ID:"3"')
    assert total == 42  # the full match count, not the page's record_count
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
def test_ticket_statistics_aggregates_over_iter_tickets(config):
    from easyvista_python_client import TicketStatistics

    respx.get(f"{ROOT}/requests").mock(side_effect=_stats_responder)
    with EasyvistaClient(config) as client:
        stats = client.ticket_statistics(dimensions=["STATUS"])
    assert isinstance(stats, TicketStatistics)
    assert stats.total == 3
    assert stats.breakdowns["STATUS"] == {"Open": 2, "Closed": 1}


@respx.mock
def test_ticket_statistics_respects_max_records(config):
    respx.get(f"{ROOT}/requests").mock(side_effect=_stats_responder)
    with EasyvistaClient(config) as client:
        stats = client.ticket_statistics(dimensions=["STATUS"], max_records=1)
    assert stats.total == 1  # capped before the second page


@respx.mock
def test_ticket_statistics_requests_field_projection(config):
    route = respx.get(f"{ROOT}/requests").mock(
        return_value=httpx.Response(
            200,
            json={"records": [], "record_count": 0, "total_record_count": 0},
        )
    )
    with EasyvistaClient(config) as client:
        client.ticket_statistics(dimensions=["URGENCY"])
    fields = route.calls.last.request.url.params["fields"]
    assert "URGENCY_ID" in fields and "RFC_NUMBER" in fields


@respx.mock
def test_resolve_memo_relative_path_and_full_url(config):
    respx.get(f"{ROOT}/requests/I1/description").mock(
        return_value=httpx.Response(200, json={"DESCRIPTION": "<p>hi</p>", "HREF": "x"})
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": ""})
    )
    with EasyvistaClient(config) as client:
        assert client.resolve_memo("requests/I1/description") == "<p>hi</p>"
        # Full URL (as returned in a record's link) resolves too; empty note -> "".
        assert client.resolve_memo(f"{ROOT}/departments/60/comment_department") == ""


@respx.mock
def test_get_department_and_comment(config):
    respx.get(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(
            200, json={"records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_FR": "ACME CORP"}]}
        )
    )
    respx.get(f"{ROOT}/departments/60/comment_department").mock(
        return_value=httpx.Response(200, json={"COMMENT_DEPARTMENT": ""})
    )
    with EasyvistaClient(config) as client:
        dept = client.get_department(60)
        note = client.get_department_comment(60)
    assert isinstance(dept, Department)
    assert dept.name == "ACME CORP"
    assert note == ""  # empty note distinguished from a 403


@respx.mock
def test_iter_departments_paginates(config):
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
    with EasyvistaClient(config) as client:
        ids = [d.department_id for d in client.iter_departments(page_size=1)]
    assert ids == [1, 2]


@respx.mock
def test_find_departments_fast_path_by_code(config):
    route = respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_CODE": "ACME-CORP"}],
                "total_record_count": 1,
            },
        )
    )
    with EasyvistaClient(config) as client:
        found = client.find_departments("ACME-CORP")
    assert [d.department_id for d in found] == [60]
    search = route.calls.last.request.url.params["search"]
    assert search == 'DEPARTMENT_CODE:"ACME-CORP"'


@respx.mock
def test_find_departments_fast_path_by_id(config):
    # An all-digit name uses the DEPARTMENT_ID fast path (not DEPARTMENT_CODE)
    # and returns on the first hit without ever falling back to iter_departments.
    route = respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"DEPARTMENT_ID": 60, "DEPARTMENT_CODE": "ACME-CORP"}],
                "total_record_count": 1,
            },
        )
    )
    with EasyvistaClient(config) as client:
        found = client.find_departments("60")
    assert [d.department_id for d in found] == [60]
    assert route.calls.last.request.url.params["search"] == 'DEPARTMENT_ID:"60"'
    assert route.call_count == 1


@respx.mock
def test_find_departments_fuzzy_fallback(config):
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
    with EasyvistaClient(config) as client:
        found = client.find_departments("acmecorp", limit=5)
    assert [d.department_id for d in found] == [60]


@respx.mock
def test_find_departments_fuzzy_scan_truncates_to_limit(config):
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
    with EasyvistaClient(config) as client:
        found = client.find_departments("acmecorp", limit=2)
    assert [d.department_id for d in found] == [60, 61]


@respx.mock
def test_find_departments_fast_path_truncates_to_limit(config):
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
    with EasyvistaClient(config) as client:
        found = client.find_departments("DUP", limit=1)
    assert [d.department_id for d in found] == [1]


@respx.mock
def test_find_departments_no_match_returns_empty(config):
    respx.get(f"{ROOT}/departments").mock(
        return_value=httpx.Response(200, json={"records": [], "total_record_count": 0})
    )
    with EasyvistaClient(config) as client:
        assert client.find_departments("ghost") == []


@respx.mock
def test_find_departments_empty_needle_returns_empty_not_everything(config):
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
    with EasyvistaClient(config) as client:
        assert client.find_departments("-") == []
        assert client.find_departments("   ") == []
    # The guard short-circuits after the fast-path miss, before iter_departments
    # ever issues its fuzzy-scan request. "-" still trips one fast-path call
    # (it survives .strip()); "   " is blank after stripping, so ev_equals_filter
    # returns None and no request is sent for it at all — hence 1, not 2.
    assert route.call_count == 1


@respx.mock
def test_get_and_search_employees(config):
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
    with EasyvistaClient(config) as client:
        emp = client.get_employee(6087)
        result = client.search_employees(search='DEPARTMENT_ID:"60"')
    assert isinstance(emp, Employee)
    assert emp.last_name == "Doe"
    assert result.records[0].employee_id == 6087


@respx.mock
def test_iter_employees_follows_pages(config):
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
    with EasyvistaClient(config) as client:
        ids = [e.employee_id for e in client.iter_employees(page_size=2)]
    assert ids == [1, 2, 3]


@respx.mock
def test_iter_employees_respects_max_records(config):
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
    with EasyvistaClient(config) as client:
        ids = [e.employee_id for e in client.iter_employees(page_size=2, max_records=1)]
    assert ids == [1]


@respx.mock
def test_create_department_and_employee(config):
    dep_route = respx.post(f"{ROOT}/departments").mock(
        return_value=httpx.Response(200, json={"HREF": f"{ROOT}/departments/61"})
    )
    emp_route = respx.post(f"{ROOT}/employees").mock(
        return_value=httpx.Response(200, json={"HREF": f"{ROOT}/employees/9001"})
    )
    respx.put(f"{ROOT}/departments/60").mock(
        return_value=httpx.Response(200, json={"records": [{"DEPARTMENT_ID": 60}]})
    )
    with EasyvistaClient(config) as client:
        dept = client.create_department(PostDepartment(department_code="NEW"))
        emp = client.create_employee(PostEmployee(last_name="Doe"))
        updated = client.update_department(60, DepartmentUpdate(manager_id=42))
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


@respx.mock
def test_get_department_context_full_assembly(config):
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
    with EasyvistaClient(config) as client:
        ctx = client.get_department_context(60, recent_tickets=1)
    assert isinstance(ctx, DepartmentContext)
    assert ctx.department.department_id == 60
    assert ctx.manager.last_name == "Boss"
    assert ctx.note == "team note"
    assert ctx.ticket_count == 5
    assert ctx.employees[0].employee_id == 1
    assert ctx.assets[0].asset_id == 7
    assert ctx.ticket_statistics is not None


@pytest.mark.parametrize("status", [403, 404])
@respx.mock
def test_get_department_context_degrades_on_403_and_404(config, status):
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
    with EasyvistaClient(config) as client:
        ctx = client.get_department_context(60)
    assert ctx.employees == []
    assert ctx.manager is None
    assert ctx.note is None
    assert ctx.ticket_count == 0
    assert ctx.recent_tickets == []
    assert ctx.ticket_statistics is None
    assert ctx.assets == []


@pytest.mark.parametrize("status", [404, 403])
@respx.mock
def test_get_department_context_manager_degrades_rest_assembles(config, status):
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
    with EasyvistaClient(config) as client:
        ctx = client.get_department_context(60)
    assert ctx.manager is None
    assert ctx.department.department_id == 60
    assert ctx.employees[0].employee_id == 1
    assert ctx.note == "note"
    assert ctx.ticket_count == 1
    assert ctx.assets[0].asset_id == 7


@respx.mock
def test_get_department_context_trim_flags_skip_related_calls(config):
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
    with EasyvistaClient(config) as client:
        ctx = client.get_department_context(
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
def test_get_department_context_rejects_unsafe_department_id(config):
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
    with EasyvistaClient(config) as client:
        with pytest.raises(ValueError):
            client.get_department_context(department_id)
    # The raise must happen before any related lookup, not be swallowed by the
    # try/except that degrades those lookups to empty lists.
    assert employees_route.call_count == 0
    assert requests_route.call_count == 0
    assert assets_route.call_count == 0
    assert comment_route.call_count == 0


@respx.mock
def test_get_department_context_rejects_blank_department_id(config):
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
    with EasyvistaClient(config) as client:
        with pytest.raises(ValueError, match="department_id is required"):
            client.get_department_context(department_id)
    assert employees_route.call_count == 0


@respx.mock
def test_update_ticket_sends_title(config):
    route = respx.put(f"{ROOT}/requests/I1").mock(
        return_value=httpx.Response(
            200, json={"RFC_NUMBER": "I1", "TITLE": "New title"}
        )
    )
    with EasyvistaClient(config) as client:
        updated = client.update_ticket("I1", RequestUpdate(title="New title"))
    assert json.loads(route.calls.last.request.content) == {"title": "New title"}
    assert updated.title == "New title"


@respx.mock
def test_find_departments_rejects_comma_injection(config):
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
    with EasyvistaClient(config) as client:
        found = client.find_departments('ALPHA",DEPARTMENT_CODE:"BETA')
    # The injected name matches no real department, so nothing should come back.
    assert found == []
    # The unsafe value must never reach the server as a filter.
    for call in route.calls:
        assert '"' not in (call.request.url.params.get("search") or "")


@respx.mock
def test_download_document_fetches_the_ddl_href(config):
    route = respx.get("https://ev.test/dl/7").mock(
        return_value=httpx.Response(200, content=b"\x89PNG\r\n\x1a\n binary")
    )
    doc = Document.model_validate(
        {"DOCUMENT": "shot.png", "DDL_HREF": "https://ev.test/dl/7"}
    )
    with EasyvistaClient(config) as client:
        content = client.download_document(doc)
    assert content == b"\x89PNG\r\n\x1a\n binary"
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_download_document_accepts_a_relative_path(config):
    respx.get(f"{ROOT}/documents/7/content").mock(
        return_value=httpx.Response(200, content=b"bytes")
    )
    with EasyvistaClient(config) as client:
        assert client.download_document("documents/7/content") == b"bytes"


def test_download_document_refuses_a_foreign_download_url(config):
    doc = Document.model_validate({"DDL_HREF": "https://attacker.test/dl/7"})
    with EasyvistaClient(config) as client:
        with pytest.raises(EasyvistaError, match="outside the configured instance"):
            client.download_document(doc)
