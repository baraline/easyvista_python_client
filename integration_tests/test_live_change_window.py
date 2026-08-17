"""Characterization of EasyVista's interval, sort and wildcard grammars.

Established live 2026-08-17 and guarded here. These tests assert *relationships*
— never fixed counts — so they hold on any instance.

The central discipline: a condition this API cannot honour is **silently
dropped** and the whole table comes back. So a single count can never prove a
range filter works — if the chosen instant sits before every record, an honoured
lower bound *also* returns everything. Every interval assertion below is
therefore a **differential across two instants**: strictly more rows at the
earlier one, and both strictly inside (0, baseline).

Skipped automatically without credentials; never runs in CI.
"""

from __future__ import annotations

import uuid
from itertools import pairwise

import pytest

from easyvista_python_client import (
    Action,
    ActionUpdate,
    EasyvistaClient,
    EasyvistaValidationError,
    PostAction,
    ev_between_filter,
    ev_contains_filter,
    ev_since_filter,
    ev_starts_with_filter,
    format_ev_datetime,
    parse_ev_datetime,
)
from easyvista_python_client._html import html_to_text

pytestmark = pytest.mark.integration


def _count(client: EasyvistaClient, search: str | None = None) -> int:
    return client.search_tickets(search=search, max_rows=1).total_record_count or 0


@pytest.fixture(scope="session")
def tickets_baseline(live_client: EasyvistaClient) -> int:
    """Unfiltered ticket count — the "condition was dropped" tell."""
    total = _count(live_client)
    if total < 4:
        pytest.skip("need at least 4 tickets to characterize a change window")
    return total


@pytest.fixture(scope="session")
def split_instants(live_client: EasyvistaClient) -> tuple[str, str]:
    """Two LAST_UPDATE literals with tickets between them, early then late.

    Sampled across four pages because the default order is not chronological, so
    one page of a large instance is a biased slice and its quartiles may not
    actually split the data.

    Returns the API's own accepted rendering (:func:`format_ev_datetime`), not
    a Python ``repr``: ``last_update`` is a parsed, timezone-aware ``datetime``
    (Task 5), so collecting it via ``.model_dump(by_alias=True)`` in "python"
    mode hands back the ``datetime`` object itself, not a string -- despite
    this fixture's own ``-> tuple[str, str]`` annotation. Interpolating that
    object straight into an f-string (as the comparison-operator test below
    does) renders Python's ``str(datetime)`` -- a space separator and 6-digit
    microseconds -- which is NOT a literal this API accepts. Sorting is done
    on the ``datetime`` values themselves (correct under differing UTC
    offsets), then each endpoint is rendered to a literal on the way out.
    """
    stamps: list = []
    for page in range(4):
        result = live_client.search_tickets(
            max_rows=200, offset=page * 200, fields=["RFC_NUMBER", "LAST_UPDATE"]
        )
        if not result.records:
            break
        for row in result.records:
            if row.last_update is not None:
                stamps.append(row.last_update)
    if len(stamps) < 8:
        pytest.skip("too few LAST_UPDATE values sampled to derive split instants")
    stamps.sort()
    early_dt, late_dt = stamps[len(stamps) // 4], stamps[(3 * len(stamps)) // 4]
    if early_dt == late_dt:
        pytest.skip("sampled LAST_UPDATE values do not span two distinct instants")
    return format_ev_datetime(early_dt), format_ev_datetime(late_dt)


def test_last_update_parses_to_an_aware_datetime(live_client: EasyvistaClient):
    """EV-R7: the model must hand back an aware datetime from real data."""
    result = live_client.search_tickets(
        max_rows=1, fields=["RFC_NUMBER", "LAST_UPDATE"]
    )
    if not result.records:
        pytest.skip("no tickets on the live instance")
    value = result.records[0].last_update
    if value is None:
        pytest.skip("sampled ticket has no LAST_UPDATE")
    # Bind before asserting: an inline assert would render the whole record (P2).
    has_zone = value.tzinfo is not None and value.utcoffset() is not None
    assert has_zone, "LAST_UPDATE parsed without a timezone offset"


def test_the_open_ended_interval_is_honoured_and_monotone(
    live_client: EasyvistaClient, split_instants, tickets_baseline
):
    """EV-R5, the decisive one: ``FIELD:(instant;)`` really bounds the result.

    Judged by a differential, never a single count. Only a genuinely applied
    lower bound returns strictly fewer rows as the instant moves later while
    both counts stay strictly inside the table.
    """
    early, late = split_instants
    search_early = ev_since_filter("LAST_UPDATE", parse_ev_datetime(early))
    search_late = ev_since_filter("LAST_UPDATE", parse_ev_datetime(late))
    # Two SEPARATE asserts, not one `and`-joined check: a compound boolean
    # that fails on the second operand would have pytest's rewriter print
    # both operands to explain it, and the other filter string here embeds a
    # live instant (P2). Neither can actually fail (`_interval_bound` returns
    # a non-empty string or raises), but the channel is closed either way.
    assert search_early is not None
    assert search_late is not None

    count_early = _count(live_client, search_early)
    count_late = _count(live_client, search_late)

    assert count_early > count_late, (
        "the interval was not applied: a later lower bound returned at least as "
        "many rows as an earlier one"
    )
    assert 0 < count_late, "the later bound matched nothing — instants unusable"
    assert count_early < tickets_baseline, (
        "the earlier bound returned the whole table, i.e. the condition was "
        "silently dropped"
    )


def test_the_closed_interval_is_honoured(
    live_client: EasyvistaClient, split_instants, tickets_baseline
):
    """The upper bound must narrow further than the lower bound alone.

    A single count strictly inside ``(0, baseline)`` cannot distinguish a
    genuinely closed interval from an upper bound that was silently dropped:
    if ``FIELD:(early;late)`` degraded to the open-ended ``FIELD:(early;)``,
    ``got`` would just equal ``count_early`` -- a value
    ``test_the_open_ended_interval_is_honoured_and_monotone`` already proves
    sits strictly inside ``(0, baseline)`` on its own, so that check alone
    would pass for the wrong reason. The extra ``count_early`` query below is
    what actually establishes the upper bound narrows the result further.
    """
    early, late = split_instants
    search = ev_between_filter("LAST_UPDATE", early, late)
    search_since_early = ev_since_filter("LAST_UPDATE", early)
    # Two separate asserts, not one `and`-joined check: see the equivalent
    # note on the open-ended interval test above (P2).
    assert search is not None
    assert search_since_early is not None

    got = _count(live_client, search)
    count_early = _count(live_client, search_since_early)

    assert 0 < got < tickets_baseline
    assert got < count_early, (
        "the closed interval matched at least as many rows as the open-ended "
        "lower bound alone -- the upper bound may have been silently dropped"
    )


def test_a_comparison_operator_never_narrows_the_result(
    live_client: EasyvistaClient, split_instants, tickets_baseline
):
    """The negative half, pinned: no comparison operator exists on this API —
    but measured live 2026-08-17, it fails two DIFFERENT ways, not one.

    The brief this test started from assumed all three renderings are
    "silently dropped" (whole table, no error). Measured against this
    instance, only the colon-free rendering actually is: ``LAST_UPDATE>="…"``
    does not match ``FIELD:"value"`` at all, so it is structurally
    unparseable and takes the same silent-ignore path as
    ``test_bare_sql_like_is_silently_ignored`` in ``test_live_search_syntax.py``.

    The other two DO use ``FIELD:"value"`` syntax, and ``LAST_UPDATE`` is a
    date-typed column, so the quoted value must actually parse as one —
    embedding ``>=`` or a ``[a TO b]`` range inside the quotes instead trips
    the **type-mismatch** fate: a hard ``EasyvistaValidationError`` (HTTP 590).
    A CONTROL below isolates that claim: a bare, valid ``LAST_UPDATE`` literal
    is asserted to be ACCEPTED (no raise), which is what licenses attributing
    the two 590s to the embedded comparison syntax specifically, rather than
    to ``FIELD:"value"`` being unusable on this column at all. Without that
    control, a future release that started honouring ``>=`` but still
    rejected this exact rendering's date shape could keep the raises green
    while the claim they guard went false -- the same "prose outran evidence"
    failure this task exists to catch, one level down.
    ``test_live_search_syntax.py`` documents the same paired shape (bogus vs.
    type-correct value) for an int column; this generalizes it to a date
    column. Asserting ``== tickets_baseline`` for the two raising cases, as
    the original version of this test did, is wrong: it happened to fail
    loudly with a 590 rather than passing for the wrong reason, but it was
    still pinning a false claim.

    Whichever fate applies, a comparison operator never narrows the result —
    it either raises or returns the whole table — so the filter builders'
    reason for existing still holds. If a future EasyVista release starts
    honouring one of these forms, this test fails and the interval builders
    can be simplified.
    """
    early, _late = split_instants

    # Control: a bare, valid LAST_UPDATE literal must be ACCEPTED. Called
    # outside `pytest.raises` on purpose -- if this column rejected
    # `FIELD:"value"` syntax outright, this call would itself raise and the
    # test would error here, honestly, rather than mis-attributing that
    # rejection to the comparison operator in the two raises below.
    control = _count(live_client, f'LAST_UPDATE:"{early}"')
    assert 0 <= control <= tickets_baseline, (
        "a bare valid LAST_UPDATE literal behaved unexpectedly -- the 590s "
        "below can no longer be attributed to the embedded comparison syntax"
    )

    with pytest.raises(EasyvistaValidationError) as excinfo:
        _count(live_client, f'LAST_UPDATE:">={early}"')
    # Bound first: `excinfo.value.status_code` renders the ExceptionInfo, and
    # with it the server's own error prose (P2).
    status_code = excinfo.value.status_code
    assert status_code == 590

    with pytest.raises(EasyvistaValidationError) as excinfo:
        _count(live_client, f'LAST_UPDATE:"[{early} TO *]"')
    status_code = excinfo.value.status_code
    assert status_code == 590

    # Only this rendering breaks FIELD:"value" structure altogether (no
    # colon), so it is the one that actually reaches the silent-ignore path.
    got = _count(live_client, f'LAST_UPDATE>="{early}"')
    assert got == tickets_baseline, (
        "a bare comparison operator was honoured — the interval builders may "
        "no longer be the only option"
    )


def test_descending_sort_needs_the_space_separated_token(
    live_client: EasyvistaClient,
):
    """EV-R6: `FIELD DESC` sorts; `FIELD:DESC` is silently ignored.

    Comparing against the UNSORTED order is what makes this meaningful — a
    monotonicity check alone cannot distinguish "sorted descending" from "the
    default order happens to be descending".
    """
    proj = ["RFC_NUMBER", "LAST_UPDATE"]

    def rfcs(sort: str | None) -> list[str | None]:
        page = live_client.search_tickets(sort=sort, fields=proj, max_rows=20)
        return [r.rfc_number for r in page.records]

    def stamps(sort: str | None) -> list:
        page = live_client.search_tickets(sort=sort, fields=proj, max_rows=20)
        return [r.last_update for r in page.records if r.last_update is not None]

    unsorted_order = rfcs(None)
    if len(unsorted_order) < 4:
        pytest.skip("need at least 4 tickets to characterize sorting")

    descending = stamps("LAST_UPDATE DESC")
    is_non_increasing = all(a >= b for a, b in pairwise(descending))
    assert is_non_increasing, "'LAST_UPDATE DESC' did not return newest-first"
    reordered = rfcs("LAST_UPDATE DESC") != unsorted_order
    assert reordered, "'LAST_UPDATE DESC' returned the default order unchanged"

    colon_ignored = rfcs("LAST_UPDATE:DESC") == unsorted_order
    assert colon_ignored, (
        "'LAST_UPDATE:DESC' now reorders results — it used to be silently "
        "ignored, and RECENT_TICKETS_SORT was changed on that basis"
    )


def test_recent_tickets_sort_token_is_honoured(live_client: EasyvistaClient):
    """The exact constant `get_department_context` relies on (O-DIR-1).

    Comparing against the UNSORTED order is what makes this meaningful, the
    same reasoning ``test_descending_sort_needs_the_space_separated_token``
    documents: monotonicity alone cannot tell "sorted descending" apart from
    "the default order happens to be descending". If the default page is
    itself already RFC-descending, this instance cannot discriminate the two
    and the test skips rather than passing for a coincidental reason.
    """
    from easyvista_python_client.directory import RECENT_TICKETS_SORT

    proj = ["RFC_NUMBER"]

    def rfcs(sort: str | None) -> list[str]:
        page = live_client.search_tickets(sort=sort, fields=proj, max_rows=20)
        # Filtered consistently on BOTH the sorted and unsorted side: an RFC-less
        # row would otherwise make `sorted_rfcs` and its own re-sorted copy
        # differ in length and fail the monotonicity check for the wrong reason.
        return [r.rfc_number for r in page.records if r.rfc_number]

    unsorted_order = rfcs(None)
    if len(unsorted_order) < 4:
        pytest.skip("need at least 4 tickets")
    if unsorted_order == sorted(unsorted_order, reverse=True):
        pytest.skip(
            "the default page order is already RFC-descending on this "
            "instance -- cannot distinguish an honoured sort token from a "
            "coincidence"
        )

    sorted_rfcs = rfcs(RECENT_TICKETS_SORT)
    is_descending = sorted_rfcs == sorted(sorted_rfcs, reverse=True)
    assert is_descending, f"{RECENT_TICKETS_SORT!r} did not return newest-first"
    reordered = sorted_rfcs != unsorted_order
    assert reordered, (
        f"{RECENT_TICKETS_SORT!r} returned the default order unchanged -- it "
        "may be silently ignored"
    )


def test_tilde_is_a_wildcard_operator_when_given_a_wildcard(
    live_client: EasyvistaClient, tickets_baseline
):
    """Corrects this suite's own earlier conclusion that `~` is exact-match.

    That held only for wildcard-free inputs. With an explicit `*`, `~` matches a
    prefix or a substring; `:` never does. Anchored on a real RFC so the prefix
    demonstrably exists.
    """
    page = live_client.search_tickets(max_rows=1, fields=["RFC_NUMBER"])
    if not page.records or not page.records[0].rfc_number:
        pytest.skip("no RFC to build a wildcard probe from")
    rfc = page.records[0].rfc_number
    if len(rfc) < 8:
        pytest.skip("RFC too short to form a strict prefix")
    prefix = rfc[:6]

    exact = _count(live_client, f'RFC_NUMBER:"{rfc}"')
    assert exact == 1

    by_prefix = _count(live_client, ev_starts_with_filter("RFC_NUMBER", prefix))
    assert exact <= by_prefix < tickets_baseline, (
        "the prefix pattern matched no more than the exact RFC, or the whole "
        "table — '~' with a wildcard is not behaving as a pattern operator"
    )

    by_contains = _count(live_client, ev_contains_filter("RFC_NUMBER", prefix))
    assert by_prefix <= by_contains < tickets_baseline

    # ':' does NOT expand a wildcard — an honest 0, not the whole table.
    colon_literal = _count(live_client, f'RFC_NUMBER:"{prefix}*"')
    assert colon_literal == 0


def test_percent_is_a_wildcard_character_just_like_star(
    live_client: EasyvistaClient, tickets_baseline
):
    """Settles whether ``%`` is really a wildcard for ``~`` — measured, not assumed.

    ``ev_contains_filter``/``ev_starts_with_filter`` (``filters.py``) reject a
    caller-supplied ``%`` on the premise that it is a wildcard character like
    ``*``, but the original probe behind that rejection only ever measured
    ``*``. Measured live 2026-08-17 on this instance: ``RFC_NUMBER~"<prefix>%"``
    and ``RFC_NUMBER~"<prefix>*"`` matched the identical, non-trivial count (32
    of 4317 tickets), both strictly more than the 1-row exact match and strictly
    fewer than the whole table. ``%`` behaves exactly as a wildcard here, so the
    builders' rejection of it is justified and should stay as is.

    Built with raw ``search=`` strings rather than the builders themselves,
    since ``ev_contains_filter``/``ev_starts_with_filter`` raise ``ValueError``
    on a ``%`` in the caller's value by design — that rejection is the very
    thing this test is checking the justification for.
    """
    page = live_client.search_tickets(max_rows=1, fields=["RFC_NUMBER"])
    if not page.records or not page.records[0].rfc_number:
        pytest.skip("no RFC to build a wildcard probe from")
    rfc = page.records[0].rfc_number
    if len(rfc) < 8:
        pytest.skip("RFC too short to form a strict prefix")
    prefix = rfc[:6]

    exact = _count(live_client, f'RFC_NUMBER:"{rfc}"')
    assert exact == 1

    by_star = _count(live_client, f'RFC_NUMBER~"{prefix}*"')
    if by_star <= exact:
        # A data-availability gap (this sampled prefix happens to be unique
        # on this instance), not a defect -- skip rather than fail (P1). The
        # sibling tilde test's non-strict `exact <= by_prefix` is the
        # precedent for treating "no wider than exact" as inconclusive, not
        # wrong.
        pytest.skip(
            "the sampled prefix's '*' match is no wider than the exact RFC "
            "on this instance -- cannot use it as the reference point for "
            "the '%' comparison"
        )
    assert by_star < tickets_baseline, (
        "the '*' prefix pattern matched the whole table -- cannot use it as "
        "the reference point for the '%' comparison"
    )

    by_percent = _count(live_client, f'RFC_NUMBER~"{prefix}%"')
    assert by_percent == by_star, (
        "'%' no longer matches the same count as '*' under '~' — it may have "
        "stopped behaving as a wildcard, which would justify relaxing the "
        "builders' rejection of a caller-supplied '%'"
    )


def test_update_action_writes_the_description_with_model_dump_casing(
    live_client: EasyvistaClient,
    live_write_client: EasyvistaClient,
    ticket_factory,
    live_action_config,
):
    """``ActionUpdate.to_api()`` ships lowercase keys — verify that lands live.

    The probe behind :meth:`EasyvistaClient.update_action` edited an action by
    sending a raw, hand-built ``{"DESCRIPTION": ...}`` body. ``ActionUpdate``
    instead goes through ``EasyvistaWriteModel.to_api()``, which calls
    ``model_dump(exclude_none=True)`` with **no aliasing** — so the body this
    client actually ships is lowercase ``{"description": ...}``, a casing
    nobody had verified live before this test. Creates exactly one action:
    an earlier probe found a *second* ``create_action`` on the same ticket can
    fail with HTTP 590.
    """
    rfc = ticket_factory()
    original_marker = f"EVCLI{uuid.uuid4().hex[:10].upper()}ORIGINAL"
    updated_marker = f"EVCLI{uuid.uuid4().hex[:10].upper()}UPDATED"

    before = {a.action_id for a in live_client.list_actions(rfc)}
    live_write_client.create_action(
        rfc,
        PostAction(
            action_type_id=int(live_action_config["action_type_id"]),
            group_id=int(live_action_config["group_id"]),
            description=original_marker,
        ),
    )
    fresh: list[Action] = [
        a for a in live_client.list_actions(rfc) if a.action_id not in before
    ]
    # Bound first: `assert len(fresh) == 1` would repr the whole list, i.e.
    # every live Action record in it (P2).
    exactly_one_new = len(fresh) == 1
    assert exactly_one_new, (
        f"expected exactly 1 new action on {rfc} after creating one, got {len(fresh)}"
    )
    action_id = fresh[0].action_id
    assert action_id is not None, "listed action carries no ACTION_ID"

    live_client.update_action(action_id, ActionUpdate(description=updated_marker))

    action = live_client.get_action(action_id)
    href = (
        action.description.get("HREF") if isinstance(action.description, dict) else None
    )
    assert href, f"action {action_id} carries no DESCRIPTION href after the update"
    text = html_to_text(live_client.resolve_memo(href) or "")

    # Both markers are self-authored nonces, so printing them is fine under P2
    # (they name nothing about the live instance), but bind first anyway to
    # keep this module's style uniform.
    landed = updated_marker in text
    stale = original_marker in text
    assert landed, (
        "update_action's lowercase-cased body did not change the DESCRIPTION "
        "memo -- ActionUpdate.to_api() ships {'description': ...} with no "
        "aliasing, and that casing had never been verified live before this"
    )
    assert not stale, "the pre-update marker is still present after the edit"
