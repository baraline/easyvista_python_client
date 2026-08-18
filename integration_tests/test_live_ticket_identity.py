"""Live coverage of ticket identity: RFC / REQUEST_ID, and the title round-trip.

Skipped without credentials; never runs in CI. Every string asserted here is one
this module or its fixtures authored (design principle P2) -- no live title,
name or label is ever compared, and no live value can reach a failure message.

Each comparison is bound to a local before it is asserted. That is not style: a
bare ``assert live_client.get_ticket(rfc).title == authored`` prints nothing
extra only while both operands are ``str``. The moment the live side is ``None``
-- exactly the state these tests exist to detect -- pytest leaves the string-diff
path and reprs the whole ``Request``, whose ``extra="allow"`` payload carries
nested DEPARTMENT and REQUESTOR labels. Asserting a bound bool leaves the
rewriter no sub-expression to explain (measured, not assumed).

This module WRITES: ``ticket_factory`` creates tickets and closes each in
teardown. Preprod only.
"""

from __future__ import annotations

import uuid

import pytest

from easyvista_python_client import (
    EasyvistaClient,
    EasyvistaValidationError,
    Request,
    RequestUpdate,
)
from integration_tests._assertions import assert_populated, assert_shape

pytestmark = pytest.mark.integration


def test_get_ticket_round_trips_the_identifier(
    live_client: EasyvistaClient, rich_ticket
):
    ticket = live_client.get_ticket(rich_ticket.rfc)
    assert_shape(ticket, Request, "get_ticket result")
    rfc_matches = ticket.rfc_number == rich_ticket.rfc
    assert rfc_matches, "RFC_NUMBER does not match the ticket that was fetched"


def test_created_ticket_carries_a_request_id(live_client: EasyvistaClient, rich_ticket):
    assert_populated(live_client.get_ticket(rich_ticket.rfc).request_id, "REQUEST_ID")


def test_rfc_number_is_derived_from_the_create_response_href(
    live_client: EasyvistaClient, ticket_factory
):
    # POST /requests returns an HREF-only body and Request._derive_rfc_from_href
    # pulls the RFC out of its trailing path segment. That is unit-tested against
    # a synthetic body; this is the assertion that the LIVE create response
    # really has that shape -- if it ever stops doing so, every caller that uses
    # ``ticket.rfc_number`` straight after a create breaks silently.
    rfc = ticket_factory()
    assert_populated(rfc, "rfc_number derived from the create response HREF")
    derived_rfc_resolves = live_client.get_ticket(rfc).rfc_number == rfc
    assert derived_rfc_resolves, (
        "the RFC derived from the create response HREF does not fetch that ticket"
    )


def test_title_round_trips_from_create(live_client: EasyvistaClient, rich_ticket):
    title_matches = live_client.get_ticket(rich_ticket.rfc).title == rich_ticket.title
    assert title_matches, "TITLE does not match the value sent on create"


def test_title_is_writable(live_client: EasyvistaClient, ticket_factory):
    # The capability RequestUpdate gained in Task 2. The update body is not
    # vendor-documented, so this test -- not the docs -- is what establishes
    # that the server accepts a title change.
    rfc = ticket_factory()
    new_title = f"EVCLI{uuid.uuid4().hex[:10].upper()}UPDATED"
    live_client.update_ticket(rfc, RequestUpdate(title=new_title))
    title_updated = live_client.get_ticket(rfc).title == new_title
    assert title_updated, "TITLE was not changed by RequestUpdate(title=...)"


def _other_live_values(
    client: EasyvistaClient, column: str, current: object, limit: int = 5
) -> list[int]:
    """Up to ``limit`` distinct ids in use on ``column``, none equal to ``current``.

    Needed because writing back the value a ticket already carries proves
    nothing: ``ticket_factory`` sets ``IMPACT_ID`` from ``live_write_config``, so
    a read-back against that same id would pass even if the field were silently
    dropped. Sampling ids that genuinely exist on the instance avoids hardcoding
    an instance-specific value.

    Several candidates, not one: an id that is in use *somewhere* is not
    necessarily legal *here*. ``IMPACT_ID`` and ``OWNER_ID`` are foreign keys
    constrained by the ticket's catalog entry, severity matrix and domain, so the
    first sampled id may be refused for a ticket ``ticket_factory`` just created.
    The caller tries them in order (see :func:`_write_first_accepted`).

    An empty list means the sampled page carries no second value at all, which
    the caller turns into a skip rather than a failure.
    """
    page = client.search_tickets(max_rows=200, fields=["RFC_NUMBER", column])
    values: list[int] = []
    for record in page.records:
        value = getattr(record, column.lower(), None)
        if value is None or value == current or value in values:
            continue
        values.append(value)
        if len(values) >= limit:
            break
    return values


def _write_first_accepted(
    client: EasyvistaClient, rfc: str, column: str, candidates: list[int]
) -> int | None:
    """PUT each candidate to ``column`` until one is accepted; return it.

    ``None`` when every candidate was refused, which the caller turns into a
    skip. A refusal here means "that id is not assignable to this ticket", not
    "``RequestUpdate`` cannot write this column" -- reporting it as the latter
    would be a false red, and this test is about the latter only.

    Only ``EasyvistaValidationError`` is caught, which is the transport's mapping
    of the two statuses a *refused value* arrives as (400 and 590). An auth
    failure, a 404 or a 5xx still reddens, because none of those means "this id
    is illegal here".
    """
    for candidate in candidates:
        try:
            client.update_ticket(rfc, RequestUpdate(**{column.lower(): candidate}))
        except EasyvistaValidationError:
            continue
        return candidate
    return None


def test_request_update_writes_impact_owner_and_external_reference(
    live_client: EasyvistaClient, ticket_factory
):
    """The three columns ``RequestUpdate`` gained on this branch, read back.

    Their unit test pins only the emitted body shape -- the client's own
    lowercase key names -- which under this branch's measured rule proves
    nothing: a 200 on a PUT is not a receipt, and a field the API cannot honour
    is silently dropped while the request succeeds. Without this, EasyVista
    renaming ``EXTERNAL_REFERENCE`` or declining ``OWNER_ID`` on this verb would
    leave the whole suite green and the public API still advertising all three.
    The same reasoning produced ``ActionUpdate``'s live guard in
    ``test_live_change_window.py``.

    One field per PUT, deliberately. A combined body that came back 200 with one
    field dropped would be exactly the failure this test exists to catch, and a
    combined body that raised would not say which field caused it.

    A PUT the instance *refuses* is not that failure. ``IMPACT_ID`` and
    ``OWNER_ID`` are foreign keys whose legal values depend on the ticket's
    catalog entry and domain, so an id sampled off another ticket may be rejected
    for this one; that is a skip, not a red. ``EXTERNAL_REFERENCE`` needs no
    instance-side legality and stays an unconditional assertion.

    P2: ``reference`` is a self-authored nonce, so it may appear in a message.
    The impact and owner ids are read off the instance and must not.
    """
    rfc = ticket_factory()
    before = live_client.get_ticket(rfc)

    # EXTERNAL_REFERENCE first and unconditionally: it is free text, so no
    # instance-side legality can stand between the PUT and the read-back, and
    # asserting it before the two foreign keys keeps this guard from being
    # skipped past when one of those cannot be established.
    reference = f"EVCLI{uuid.uuid4().hex[:10].upper()}REF"  # 18 chars; cap is 50
    live_client.update_ticket(rfc, RequestUpdate(external_reference=reference))
    reference_landed = live_client.get_ticket(rfc).external_reference == reference
    assert reference_landed, (
        f"EXTERNAL_REFERENCE is not {reference} after "
        "RequestUpdate(external_reference=...) -- the field was accepted with a "
        "200 and silently dropped"
    )

    # IMPACT_ID and OWNER_ID are foreign keys, and an id in use on another ticket
    # is not necessarily assignable to this one, so a refusal is a skip: several
    # candidates are tried, and only if none is accepted does the column go
    # unmeasured. Failing there would report "RequestUpdate cannot write
    # OWNER_ID" when what happened is "that owner is not valid for this ticket".
    new_impact = _write_first_accepted(
        live_client,
        rfc,
        "IMPACT_ID",
        _other_live_values(live_client, "IMPACT_ID", before.impact_id),
    )
    new_owner = _write_first_accepted(
        live_client,
        rfc,
        "OWNER_ID",
        _other_live_values(live_client, "OWNER_ID", before.owner_id),
    )
    if new_impact is None or new_owner is None:
        # P2: no sampled id is named, only the column names authored here.
        pytest.skip(
            "no sampled IMPACT_ID / OWNER_ID differing from this ticket's own "
            "was accepted for it -- cannot distinguish an honoured write from a "
            "dropped one"
        )

    after = live_client.get_ticket(rfc)
    impact_landed = after.impact_id == new_impact
    owner_landed = after.owner_id == new_owner
    assert impact_landed, (
        "IMPACT_ID does not match the id sent by RequestUpdate(impact_id=...)"
    )
    assert owner_landed, (
        "OWNER_ID does not match the id sent by RequestUpdate(owner_id=...)"
    )


def test_update_does_not_disturb_the_identifier(
    live_client: EasyvistaClient, ticket_factory
):
    rfc = ticket_factory()
    live_client.update_ticket(
        rfc, RequestUpdate(title=f"EVCLI{uuid.uuid4().hex[:10].upper()}RENAMED")
    )
    rfc_survived_update = live_client.get_ticket(rfc).rfc_number == rfc
    assert rfc_survived_update, "RFC_NUMBER changed across a title update"
