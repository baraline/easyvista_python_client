"""Claims about the async fan-out that have no sync twin.

Hand-written on this side, like ``_concurrency.py`` itself.
``unasync_build.py`` excludes both by name, because these assertions are not
the sync ones differently spelled -- they are about a different primitive.
The sync twin asserts that ``settle`` preserves order and evaluated its
arguments in sequence; neither claim exists here.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from easyvista_python_client._async._concurrency import Semaphore, settle
from easyvista_python_client._async.client import _ACTION_FANOUT, AsyncEasyvistaClient
from easyvista_python_client.exceptions import EasyvistaError, EasyvistaNotFound
from easyvista_python_client.models.action import Action
from easyvista_python_client.models.request import PostRequest

ROOT = "https://ev.test/api/v1/acme"


# --- the settle/Semaphore primitives -----------------------------------------


async def test_settle_preserves_source_order_not_completion_order():
    """A slow first branch still lands first in the result list."""

    async def slow():
        await asyncio.sleep(0.02)
        return "first"

    async def fast():
        return "second"

    assert await settle(slow(), fast()) == ["first", "second"]


async def test_settle_raises_the_first_failure_in_source_order():
    """Not whichever failed soonest on the clock."""

    async def slow_boom():
        await asyncio.sleep(0.02)
        raise ValueError("slow")

    async def fast_boom():
        raise KeyError("fast")

    with pytest.raises(ValueError, match="slow"):
        await settle(slow_boom(), fast_boom())


async def test_settle_awaits_every_sibling_before_raising():
    """No request outlives the method that issued it.

    A bare ``asyncio.gather`` propagates the first exception while its
    siblings keep running, and those orphans can still be in flight when
    ``__aexit__`` closes the client.
    """
    finished: list[str] = []

    async def boom():
        raise RuntimeError("boom")

    async def sibling():
        await asyncio.sleep(0.02)
        finished.append("sibling")

    with pytest.raises(RuntimeError):
        await settle(boom(), sibling())
    assert finished == ["sibling"]


async def test_settle_of_nothing_is_empty():
    assert await settle() == []


async def test_the_semaphore_actually_bounds_concurrency():
    """The async Semaphore is a real ceiling, not a stand-in."""
    limiter = Semaphore(2)
    in_flight = 0
    peak = 0

    async def one():
        nonlocal in_flight, peak
        async with limiter:
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

    await settle(*(one() for _ in range(6)))
    assert peak <= 2


@respx.mock
def test_the_action_limiter_is_built_per_call(config):
    """``_resolve_action_bodies`` survives being driven from a second loop.

    An ``asyncio.Semaphore`` binds to the first event loop that *contends* it,
    and raises ``RuntimeError: ... is bound to a different event loop`` when a
    second one does. Hoisting ``Semaphore(_ACTION_FANOUT)`` out of
    ``_resolve_action_bodies`` onto ``self`` or module scope is therefore a
    real regression, and this is the lock on it: one client, two separate
    ``asyncio.run`` calls, both resolving the same fan-out.

    Two details make it bite. The fan-out is deliberately **wider than
    ``_ACTION_FANOUT``**, because an uncontended acquire never touches the loop
    at all -- that is exactly why a hoisted limiter passes every low-traffic
    test and only fails in production under load. And the mocked handler
    sleeps, so the branches genuinely overlap rather than completing one at a
    time and never exhausting the limiter.

    Deliberately a plain ``def``: it drives two loops of its own with
    ``asyncio.run``, which raises if it is called from inside a running loop --
    and ``asyncio_mode = "auto"`` would supply exactly that.
    """
    count = _ACTION_FANOUT + 4

    async def _responder(request):
        await asyncio.sleep(0.01)
        action_id = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ACTION_ID": action_id, "DESCRIPTION": "note"})

    for i in range(1, count + 1):
        respx.get(f"{ROOT}/actions/{i}").mock(side_effect=_responder)

    listed = [Action.model_validate({"ACTION_ID": i}) for i in range(1, count + 1)]
    client = AsyncEasyvistaClient(config)

    async def resolve():
        return await client._resolve_action_bodies(list(listed))

    first = asyncio.run(resolve())
    second = asyncio.run(resolve())
    asyncio.run(client.aclose())

    expected = list(range(1, count + 1))
    assert [a.action_id for a in first] == expected
    assert [a.action_id for a in second] == expected
    assert [a.description for a in second] == ["note"] * count


# --- the client's fan-outs ----------------------------------------------------
#
# The async client used to be the sync client with `await` inserted: it issued
# every request serially and so was no faster than the sync one (measured
# against a live instance on a 19-action ticket: 14.65s async vs 13.44s sync).
# These tests pin that the independent requests now actually overlap.
#
# Asserting on results alone cannot do that -- the results are identical either
# way, which is the whole point, and that identity is exactly what the generated
# sync suite covers. So each test here measures PEAK OVERLAP through a mock that
# holds the connection open, and
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

    ``get_ticket`` is issued first and outside the fan-out on purpose -- it is
    the only call with no fallback, so a wrong RFC must cost one request rather
    than five. A peak of exactly 4 proves both halves at once: the four
    overlapped, and the ticket GET did not join them.
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
    order. The generated sync suite mocks with ``return_value=``, which is
    order-agnostic and would stay green under a shuffle; only a surface that
    can complete out of order can make this claim at all.
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
    the description failure -- the one the sequential surface would have hit.
    A bare ``gather`` (no ``return_exceptions=True``) raises the documents one
    instead, so this is the permanent lock against that simplification. On the
    sync surface the question cannot arise: the first failure is the only one
    ever evaluated.
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
    """The 403-only asymmetry survives concurrent evaluation.

    ``list_actions`` and ``list_documents`` catch ``EasyvistaAuthError`` ONLY,
    so a 404 there propagates and fails the whole bundle, while the memos
    degrade on both 403 and 404. On a fan-out that runs every branch to
    completion the failure has to survive the settling step to be raised at
    all, which is what makes this worth pinning here as well as in the
    generated suite.
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

    ``get_department`` is issued first and outside the fan-out because the
    manager lookup needs its ``MANAGER_ID``. The tracker covers only the branch
    routes, so the peak is evidence the branches overlap each other rather than
    that something overlapped the department GET.
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
