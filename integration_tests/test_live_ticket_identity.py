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

from easyvista_python_client import EasyvistaClient, Request, RequestUpdate
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


def test_update_does_not_disturb_the_identifier(
    live_client: EasyvistaClient, ticket_factory
):
    rfc = ticket_factory()
    live_client.update_ticket(
        rfc, RequestUpdate(title=f"EVCLI{uuid.uuid4().hex[:10].upper()}RENAMED")
    )
    rfc_survived_update = live_client.get_ticket(rfc).rfc_number == rfc
    assert rfc_survived_update, "RFC_NUMBER changed across a title update"
