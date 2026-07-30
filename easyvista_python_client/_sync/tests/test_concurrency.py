"""The sync concurrency twin behaves as the async one's counterpart.

Hand-written on this side, like ``_concurrency.py`` itself. The async twin
asserts that ``settle`` overlaps work, settles siblings before raising, and
that the semaphore is a real ceiling. None of those claims exists here. What
must hold is that the sequential ``settle`` keeps the contract callers rely
on -- results matched to arguments by position -- and that the ``Semaphore``
stand-in is inert rather than accidentally serialising or raising.

The wire-order test at the bottom is the same kind of claim seen from the
other end: because ``settle`` receives already-evaluated arguments, a fan-out's
meaning here is "left to right", and that ordering is what makes this client
issue the same requests in the same order the pre-migration sequential code
did. The async surface cannot assert it -- it issues them concurrently.
"""

from __future__ import annotations

import httpx
import respx

from easyvista_python_client._sync._concurrency import Semaphore, settle
from easyvista_python_client._sync.client import _ACTION_FANOUT, EasyvistaClient
from easyvista_python_client.models.action import Action

ROOT = "https://ev.test/api/v1/acme"


def test_settle_preserves_argument_order():
    """Results come back positionally."""
    assert settle("a", "b", "c") == ["a", "b", "c"]


def test_settle_of_nothing_is_empty():
    assert settle() == []


def test_settle_receives_arguments_already_evaluated_in_order():
    """This is the whole reason the no-op is correct.

    Stripping ``await`` makes each argument expression evaluate eagerly where
    it is written, so a fan-out's sync meaning is "left to right".
    """
    order: list[str] = []

    def branch(name):
        order.append(name)
        return name

    assert settle(branch("a"), branch("b")) == ["a", "b"]
    assert order == ["a", "b"]


def test_a_raise_in_an_earlier_argument_skips_the_later_ones():
    """Matching the sequential client, which never reached the later call."""
    reached: list[str] = []

    def boom():
        raise RuntimeError("boom")

    def later():
        reached.append("later")
        return "later"

    try:
        settle(boom(), later())
    except RuntimeError:
        pass
    assert reached == []


def test_the_semaphore_is_inert():
    """It accepts a width, ignores it, and never blocks."""
    limiter = Semaphore(2)
    with limiter:
        with limiter:
            assert True


@respx.mock
def test_the_action_limiter_never_caps_the_fan_out(config):
    """More actions than ``_ACTION_FANOUT`` resolve, twice, on one client.

    The async twin of this test drives ``_resolve_action_bodies`` from two
    separate event loops, because there an ``asyncio.Semaphore`` binds to the
    first loop that contends it and a hoisted one would raise on the second.
    Here there is no loop and nothing to bind, so that claim does not exist.
    What must hold instead is that the stand-in really is inert: a width of
    ``_ACTION_FANOUT`` must not cap a wider fan-out, block it, or carry state
    from one call into the next. A stand-in that actually counted -- and never
    released, since there is no scheduler to release into -- would hang or
    truncate here, and every other test in the pair would stay green.
    """
    count = _ACTION_FANOUT + 4

    def responder(request):
        action_id = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ACTION_ID": action_id, "DESCRIPTION": "note"})

    for i in range(1, count + 1):
        respx.get(f"{ROOT}/actions/{i}").mock(side_effect=responder)

    listed = [Action.model_validate({"ACTION_ID": i}) for i in range(1, count + 1)]
    expected = list(range(1, count + 1))
    with EasyvistaClient(config) as client:
        first = client._resolve_action_bodies(list(listed))
        second = client._resolve_action_bodies(list(listed))

    assert [a.action_id for a in first] == expected
    assert [a.action_id for a in second] == expected
    assert [a.description for a in second] == ["note"] * count


def _branch_label(request):
    """Name the department-context branch a recorded request belongs to.

    Three of the seven branches hit ``/requests`` and are told apart by what
    they ask for: ``count_tickets`` caps at one row, ``recent_tickets`` sorts,
    and ``ticket_statistics`` projects a field list.
    """
    path = request.url.path
    params = request.url.params
    if path.endswith("/requests"):
        if params.get("max_rows") == "1":
            return "ticket_count"
        if "sort" in params:
            return "recent"
        return "statistics"
    return path.rsplit("/api/v1/acme", 1)[-1]


@respx.mock
def test_department_context_issues_its_branches_in_source_order(config):
    """The seven branches reach the wire left to right, in the written order.

    ``settle``'s arguments are evaluated before it is entered, so the order
    they are written in -- ``_employees, _manager, _note, _ticket_count,
    _recent, _statistics, _assets`` -- *is* the order this client issues them
    in. That is the only thing making it match the pre-migration sequential
    code's wire order, and nothing else checks it: reordering the arguments
    leaves every result identical and every other test green.

    The async twin cannot make this claim, which is why it lives here rather
    than in the generated suite. It asserts the complementary one -- that the
    same seven overlap.
    """
    seen: list[str] = []

    def responder(request):
        seen.append(_branch_label(request))
        path = request.url.path
        if path.endswith("/departments/60"):
            return httpx.Response(
                200, json={"records": [{"DEPARTMENT_ID": 60, "MANAGER_ID": 9}]}
            )
        if path.endswith("/comment_department"):
            return httpx.Response(200, json={"COMMENT_DEPARTMENT": "note"})
        if path.endswith("/employees/9"):
            return httpx.Response(200, json={"records": [{"EMPLOYEE_ID": 9}]})
        return httpx.Response(
            200, json={"records": [], "record_count": 0, "total_record_count": 0}
        )

    respx.route().mock(side_effect=responder)
    with EasyvistaClient(config) as client:
        context = client.get_department_context(60)

    assert context.department.department_id == 60
    assert seen == [
        "/departments/60",
        "/employees",
        "/employees/9",
        "/departments/60/comment_department",
        "ticket_count",
        "recent",
        "statistics",
        "/assets",
    ]
