"""Live smoke tests against a real EasyVista instance.

Skipped automatically unless credentials are configured, via ``EASYVISTA_TEST_*``
env vars or ``secrets/easyvista_test_*`` files. Never runs in CI (which runs
``pytest -m "not integration"``). NEVER point at production.

This module WRITES. It creates up to three tickets and closes every one:

* one under-specified create the server is expected to reject -- which still
  creates the row (measured: 9 of 9 rejected creates left one), so it is
  reconciled by its ``external_reference`` marker and closed. An earlier version
  of this file claimed "no ticket persists from this module ... read-only-safe by
  construction"; that was wrong and leaked one ticket per live run;
* one create with the full documented body, to prove the ids land;
* one from ``ticket_factory`` for the ``set_status`` check.

The ticket-creating fixture lives in ``conftest.py`` and is also used by
``test_live_search_syntax``.

Every assertion here is by shape, and every one routes through ``_assertions``
or a pre-bound local (design principle P2). pytest's assertion rewriter reports
the sub-expressions of a failing assert, so ``assert isinstance(ticket,
Request)`` prints the whole live record, ``assert len(result.records) <= 1``
prints every record in it, and ``assert ei.value.status_code == 590`` renders
the ExceptionInfo -- which includes the server's own error text, prose this
suite did not author. Measured, not assumed. ``assert_shape`` lives in a module
pytest does not rewrite, so only its label is ever rendered; ``all(... for
...)`` reduces to a bare ``False`` because the rewriter cannot explain inside a
generator expression.
"""

from __future__ import annotations

import uuid

import pytest

from easyvista_python_client import (
    Action,
    Asset,
    Document,
    EasyvistaClient,
    EasyvistaError,
    EasyvistaValidationError,
    PostRequest,
    Request,
    ev_equals_filter,
)
from integration_tests._assertions import assert_shape

pytestmark = pytest.mark.integration


def test_search_tickets_read_only(live_client: EasyvistaClient) -> None:
    result = live_client.search_tickets(max_rows=1)
    total = result.total_record_count
    assert_shape(total, int, "requests TOTAL_RECORD_COUNT")
    assert total >= 0
    at_most_one = len(result.records) <= 1
    assert at_most_one, "max_rows=1 returned more than one record"
    assert all(isinstance(r, Request) for r in result.records)


def test_get_ticket(live_client: EasyvistaClient, sample_rfc: str) -> None:
    ticket = live_client.get_ticket(sample_rfc)
    assert_shape(ticket, Request, "get_ticket result")
    rfc_round_trips = ticket.rfc_number == sample_rfc
    assert rfc_round_trips, "RFC_NUMBER does not match the ticket requested"


def test_search_assets_read_only(live_client: EasyvistaClient) -> None:
    result = live_client.search_assets(max_rows=1)
    total = result.total_record_count
    assert_shape(total, int, "assets TOTAL_RECORD_COUNT")
    assert total >= 0
    at_most_one = len(result.records) <= 1
    assert at_most_one, "max_rows=1 returned more than one record"
    assert all(isinstance(a, Asset) for a in result.records)


def test_list_actions(live_client: EasyvistaClient, sample_rfc: str) -> None:
    # Lists via the top-level GET /actions?search=REQUEST.RFC_NUMBER:"{rfc}" endpoint.
    actions = live_client.list_actions(sample_rfc)
    assert_shape(actions, list, "list_actions result")
    assert all(isinstance(a, Action) for a in actions)


def test_list_documents(live_client: EasyvistaClient, sample_rfc: str) -> None:
    # Validates the O5 best-guess endpoint (GET requests/{rfc}/documents) live.
    documents = live_client.list_documents(sample_rfc)
    assert_shape(documents, list, "list_documents result")
    assert all(isinstance(d, Document) for d in documents)


def test_classify_fields_live_ticket(
    live_client: EasyvistaClient, sample_rfc: str
) -> None:
    fc = live_client.get_ticket(sample_rfc).classify_fields()
    assert all(k.upper().startswith("E_") for k in fc.custom)  # custom bucket is e_*
    assert all("AVAILABLE_FIELD_" in k.upper() for k in fc.available)


def test_an_underspecified_create_body_raises_validation_error(
    live_client: EasyvistaClient,
    live_write_client: EasyvistaClient,
    live_write_config: dict[str, str],
    sample_catalog_code: str,
) -> None:
    """A create missing the documented ids is rejected 590, not retried as 5xx.

    This test used to send ``PostRequest(catalog_code=...)`` and attribute the
    590 to the missing *title*. Both halves of that were wrong, measured:

    * ``title`` is NOT the mandatory field. The full documented body with no
      title at all creates successfully. What the old payload actually omitted
      was ``origin``/``department_id``/``urgency_id``/``impact_id``, so the
      assertion never tested the thing it named.
    * it claimed "no ticket created ... read-only-safe by construction". A
      rejected create on this API **does** create the row -- 9 of 9 rejections
      left one -- so the old test leaked a ticket on every single live run.

    So the omission is now the documented ids (which really are required here),
    and the ticket the rejection leaves behind is reconciled and closed. The
    ``external_reference`` marker survives the failed insert and is searchable,
    which is the only handle available: no ``RFC_NUMBER`` comes back from a
    rejected create.
    """
    marker = f"EVCLI{uuid.uuid4().hex[:10].upper()}"
    try:
        with pytest.raises(EasyvistaValidationError) as ei:
            live_write_client.create_ticket(
                PostRequest(
                    catalog_code=sample_catalog_code,
                    title=marker,
                    description=f"{marker} under-specified create; safe to close",
                    external_reference=marker,
                )
            )
        # Bound first: asserting on `ei.value.status_code` makes the rewriter
        # render the ExceptionInfo, and that prints the exception's own message --
        # server prose this suite did not author (P2).
        status_code = ei.value.status_code
        assert status_code == 590, "an under-specified create did not raise HTTP 590"
    finally:
        # Runs even when the create unexpectedly SUCCEEDS, because that outcome
        # leaves a ticket too and an assertion failure must not also orphan one.
        _close_by_marker(live_client, live_write_config, marker)


def test_the_documented_create_body_lands_every_id(
    live_client: EasyvistaClient,
    live_write_client: EasyvistaClient,
    live_write_config: dict[str, str],
    sample_catalog_code: str,
) -> None:
    """The documented create body is accepted and every id it carries persists.

    The counterpart to the test above, and the reason this suite can trust any
    create at all. ``origin``/``department_id``/``urgency_id``/``impact_id`` are
    read back and compared to what was sent.

    The read is **explicitly projected**. It has to be: these columns are absent
    from the default search projection exactly like ``TITLE``, so an unprojected
    read returns ``None`` for all of them and would pass this test by comparing
    two absences.
    """
    cfg = live_write_config
    marker = f"EVCLI{uuid.uuid4().hex[:10].upper()}"
    try:
        created = live_write_client.create_ticket(
            PostRequest(
                catalog_code=sample_catalog_code,
                title=marker,
                description=f"{marker} documented create body; safe to close",
                origin=int(cfg["origin"]),
                department_id=int(cfg["department_id"]),
                urgency_id=int(cfg["urgency_id"]),
                impact_id=int(cfg["impact_id"]),
                external_reference=marker,
            )
        )
        rfc = created.rfc_number
        assert rfc, "the documented create body returned no RFC_NUMBER"
        rows = live_client.search_tickets(
            search=ev_equals_filter("RFC_NUMBER", rfc),
            fields=[
                "RFC_NUMBER",
                "URGENCY_ID",
                "IMPACT_ID",
                "REQUEST_ORIGIN_ID",
                "EXTERNAL_REFERENCE",
            ],
            max_rows=1,
        )
        record = rows.records[0] if rows.records else None
        assert record is not None, "the created ticket was not readable back"
        # Every comparison binds a bool before asserting, so a mismatch cannot
        # print the instance's own values (P2).
        urgency_matches = str(record.urgency_id) == str(cfg["urgency_id"])
        impact_matches = str(record.impact_id) == str(cfg["impact_id"])
        marker_matches = record.external_reference == marker
        assert urgency_matches, "URGENCY_ID did not survive the documented create"
        assert impact_matches, "IMPACT_ID did not survive the documented create"
        assert marker_matches, "EXTERNAL_REFERENCE did not survive the create"
    finally:
        _close_by_marker(live_client, live_write_config, marker)


def test_set_status_reaches_a_non_terminal_status(
    live_client: EasyvistaClient,
    live_write_client: EasyvistaClient,
    live_write_config: dict[str, str],
    ticket_factory,
) -> None:
    """``set_status`` sets an arbitrary status, not only a closing one.

    The API has no flat status update -- ``RequestUpdate`` carries no
    ``status_id`` for that reason -- and the ``{"closed": {"status_GUID": ...}}``
    envelope is the only route. Its wire name suggests it only closes; measured,
    it reaches every status tried.

    This pins the non-terminal case specifically, because that is the surprising
    half and the half a future reader is most likely to "simplify" away. The GUID
    is read off the instance rather than hardcoded: status GUIDs are per-instance
    configuration, so a literal here would be a value this repo must not carry
    and would be wrong on any other deployment anyway.
    """
    rfc = ticket_factory()
    before = live_client.get_ticket(rfc).status_id
    target_guid, target_id = _a_different_status(live_client, exclude=before)
    if target_guid is None:
        pytest.skip("no second status with a readable GUID on this instance")

    live_write_client.set_status(
        rfc, status_guid=target_guid, comment="capability-suite status probe"
    )
    after = live_client.get_ticket(rfc).status_id
    # Bound as bools: the ids are instance configuration, not suite-authored (P2).
    moved = str(after) != str(before)
    landed_on_target = str(after) == str(target_id)
    assert moved, "set_status did not change the ticket's status"
    assert landed_on_target, "set_status landed on a status other than the one asked"


def _close_by_marker(client: EasyvistaClient, cfg: dict[str, str], marker: str) -> None:
    """Close every ticket carrying ``marker``, however it got there.

    The cleanup a rejected create needs. No ``RFC_NUMBER`` comes back from one,
    so the marker is the only handle -- and it does survive the failed insert
    (measured). Searching rather than tracking is the point: a tracked list can
    only hold ids the caller was given, which is precisely the set that excludes
    every orphan.

    Never raises. It runs in a ``finally`` beside the assertion that matters, and
    a cleanup failure must not replace a real test result.
    """
    try:
        found = client.search_tickets(
            search=ev_equals_filter("EXTERNAL_REFERENCE", marker),
            fields=["RFC_NUMBER"],
            max_rows=20,
        )
    except EasyvistaError:
        return
    for record in found.records:
        rfc = record.rfc_number
        if not rfc:
            continue
        try:
            client.close_ticket(
                rfc, status_guid=cfg["status_guid"], comment="smoke cleanup"
            )
        except EasyvistaError:
            continue


def _a_different_status(
    client: EasyvistaClient, *, exclude: object
) -> tuple[str | None, str | None]:
    """Return ``(status_guid, status_id)`` for some status that is not ``exclude``.

    Read off the instance because status GUIDs are per-instance configuration: a
    literal would be a value this repo must not carry, and would be wrong on any
    other deployment. Found by sampling tickets and taking the first whose status
    differs -- the nested ``STATUS`` object carries both the id and the GUID,
    but only on an UNPROJECTED read, so no ``fields`` is passed here.
    """
    try:
        sampled = client.search_tickets(sort="LAST_UPDATE DESC", max_rows=60)
    except EasyvistaError:
        return None, None
    for record in sampled.records:
        status = record.model_extra.get("STATUS") if record.model_extra else None
        if not isinstance(status, dict):
            continue
        sid = status.get("STATUS_ID")
        guid = status.get("STATUS_GUID")
        if sid is None or not guid:
            continue
        if str(sid) != str(exclude):
            return str(guid), str(sid)
    return None, None
