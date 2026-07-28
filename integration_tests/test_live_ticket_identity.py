"""Live coverage of ticket identity: RFC / REQUEST_ID, and the title round-trip.

Skipped without credentials; never runs in CI. Every string asserted here is one
this module or its fixtures authored (design principle P2) -- no live title,
name or label is ever compared, and no live value can reach a failure message.

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
    assert ticket.rfc_number == rich_ticket.rfc


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
    assert live_client.get_ticket(rfc).rfc_number == rfc


def test_title_round_trips_from_create(live_client: EasyvistaClient, rich_ticket):
    assert live_client.get_ticket(rich_ticket.rfc).title == rich_ticket.title


def test_title_is_writable(live_client: EasyvistaClient, ticket_factory):
    # The capability RequestUpdate gained in Task 2. The update body is not
    # vendor-documented, so this test -- not the docs -- is what establishes
    # that the server accepts a title change.
    rfc = ticket_factory()
    new_title = f"EVCLI{uuid.uuid4().hex[:10].upper()}UPDATED"
    live_client.update_ticket(rfc, RequestUpdate(title=new_title))
    assert live_client.get_ticket(rfc).title == new_title


def test_update_does_not_disturb_the_identifier(
    live_client: EasyvistaClient, ticket_factory
):
    rfc = ticket_factory()
    live_client.update_ticket(
        rfc, RequestUpdate(title=f"EVCLI{uuid.uuid4().hex[:10].upper()}RENAMED")
    )
    assert live_client.get_ticket(rfc).rfc_number == rfc
