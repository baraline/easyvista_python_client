"""Invoke every public client method against a mocked socket.

The existing suites cover endpoints one at a time and assert payload shapes.
This asserts something different and much cheaper to keep true: that *every*
public method on both clients still reaches HTTP and returns without blowing
up, and that the two surfaces stay the same size.

Why it matters: when the sync tree becomes generated from the async one, the
failure mode is not a subtly wrong payload -- it is a method that no longer
dispatches at all, or that raises ``TypeError`` the moment it is called. A
per-endpoint suite catches that only where a test happens to exist. This
catches it everywhere, and fails loudly on a method added with no coverage.

Only the socket is replaced. URL building, header assembly, the retry
wrapper, error mapping and model parsing all execute for real.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
import respx

from easyvista_python_client import (
    ActionUpdate,
    AsyncEasyvistaClient,
    DepartmentUpdate,
    EasyvistaClient,
    EmployeeUpdate,
    PostAction,
    PostAsset,
    PostDepartment,
    PostEmployee,
    PostRequest,
    PostTask,
    RequestUpdate,
)

#: One payload that satisfies every parser in the package.
#:
#: ``extract_records`` returns the ``records`` list when present and falls back
#: to ``[data]`` for a bare dict, and ``_first_record_parser`` validates
#: ``records[0]``. So a search sees a one-record page with real counts, and a
#: single-record get/create/update sees that same record. ``parse_memo`` finds
#: no matching field and returns ``None``, which is a legal ``resolve_memo``
#: result. ``ASSET_ID`` must be an int -- ``Asset`` rejects a string.
PAYLOAD = {
    "records": [
        {
            "RFC_NUMBER": "I1",
            "ACTION_ID": 1,
            "ASSET_ID": 1,
            "DEPARTMENT_ID": 1,
            "EMPLOYEE_ID": 1,
        }
    ],
    "record_count": "1",
    "total_record_count": "1",
}

#: Methods that deliberately never reach HTTP, with the reason.
#: Anything else making zero requests is a wiring failure.
NO_TRANSPORT = {
    "close": "releases the httpx client only",
    "aclose": "releases the httpx client only",
    "from_env": "classmethod constructor, performs no I/O",
}

#: Positional and keyword arguments for every method that does reach HTTP.
ARGS: dict[str, tuple[tuple, dict]] = {
    "add_document": (("I1",), {"filename": "d.txt", "content": b"x"}),
    # The escape hatch: an arbitrary route, parsed by nobody. PAYLOAD satisfies
    # it because `send` returns the raw JSON body unchanged.
    "send": (("GET", "requests"), {}),
    "close_ticket": (("I1",), {}),
    "set_status": (("I1",), {"status_guid": "{0000-0000}"}),
    "count_tickets": ((), {}),
    "create_action": (("I1", PostAction()), {}),
    "create_task": (("I1", PostTask(action_type_id=94, group_id=3)), {}),
    "create_asset": ((PostAsset(catalog_id=1),), {}),
    "create_department": ((PostDepartment(),), {}),
    "create_employee": ((PostEmployee(),), {}),
    "create_ticket": ((PostRequest(catalog_code="C"),), {}),
    "create_tickets": (([PostRequest(catalog_code="C")],), {}),
    "delete_document": (("I1", "d1"), {}),
    "download_document": (("requests/I1/documents/1",), {}),
    "find_departments": (("Acme",), {}),
    "get_action": ((1,), {}),
    "get_asset": (("A1",), {}),
    "get_department": ((1,), {}),
    "get_department_comment": ((1,), {}),
    "get_department_context": ((1,), {}),
    "get_employee": ((1,), {}),
    "get_ticket": (("I1",), {}),
    "get_ticket_context": (("I1",), {}),
    "iter_actions": (("I1",), {"max_records": 1}),
    "iter_assets": ((), {"max_records": 1}),
    "iter_departments": ((), {"max_records": 1}),
    "iter_employees": ((), {"max_records": 1}),
    "iter_tickets": ((), {"max_records": 1}),
    "list_actions": (("I1",), {}),
    "list_documents": (("I1",), {}),
    "resolve_memo": (("requests/I1/description",), {}),
    "search_assets": ((), {}),
    "search_departments": ((), {}),
    "search_employees": ((), {}),
    "search_tickets": ((), {}),
    "stream_document": (("requests/I1/documents/1",), {}),
    "ticket_statistics": ((), {"max_records": 1}),
    "update_action": ((1, ActionUpdate()), {}),
    "update_department": ((1, DepartmentUpdate()), {}),
    "update_employee": ((1, EmployeeUpdate()), {}),
    "update_ticket": (("I1", RequestUpdate()), {}),
}


def _public(cls: type) -> set[str]:
    """Every callable public attribute on ``cls``."""
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


def test_every_public_method_is_covered_by_this_module():
    """A new public method must be added to ARGS or NO_TRANSPORT."""
    known = set(ARGS) | set(NO_TRANSPORT)
    for cls in (EasyvistaClient, AsyncEasyvistaClient):
        missing = _public(cls) - known
        assert not missing, f"{cls.__name__} has no invocation entry: {missing}"


def test_the_two_surfaces_are_the_same_size():
    """The surfaces differ only in how the client is released."""
    assert _public(EasyvistaClient) - _public(AsyncEasyvistaClient) == {"close"}
    assert _public(AsyncEasyvistaClient) - _public(EasyvistaClient) == {"aclose"}


@pytest.mark.parametrize("name", sorted(ARGS))
@respx.mock
def test_sync_method_reaches_the_transport(name, config):
    route = respx.route().mock(return_value=httpx.Response(200, json=PAYLOAD))
    args, kwargs = ARGS[name]
    with EasyvistaClient(config) as client:
        result = getattr(client, name)(*args, **kwargs)
        if inspect.isgenerator(result):
            list(result)
    assert route.called, f"{name} issued no request"


@pytest.mark.parametrize("name", sorted(ARGS))
@respx.mock
async def test_async_method_reaches_the_transport(name, config):
    route = respx.route().mock(return_value=httpx.Response(200, json=PAYLOAD))
    args, kwargs = ARGS[name]
    async with AsyncEasyvistaClient(config) as client:
        result = getattr(client, name)(*args, **kwargs)
        if inspect.isasyncgen(result):
            [item async for item in result]
        else:
            await result
    assert route.called, f"{name} issued no request"
