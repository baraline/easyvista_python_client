"""Live coverage of ticket metadata: status, urgency, impact, dates and GTR.

Skipped without credentials; never runs in CI. Values authored by this suite are
compared directly; instance content is asserted by shape only, and every
instance-specific field routes through ``require_field`` so an instance without
it skips rather than fails (design principles P1 and P2).

Reads a shared session ticket -- it mutates nothing.
"""

from __future__ import annotations

import uuid

import pytest

from easyvista_python_client import EasyvistaClient, RequestUpdate
from easyvista_python_client._html import html_to_text
from integration_tests._assertions import assert_populated, require_field

pytestmark = pytest.mark.integration

# Official, portable across EasyVista deployments -- declared on Request.
OFFICIAL_TIME_FIELDS = (
    "creation_date_ut",
    "submit_date_ut",
    "max_resolution_date_ut",
    "expected_date_ut",
    "end_date_ut",
    "last_update",
    "sla_id",
    "time_used_to_solve_request",
)

# Instance-specific -- NOT declared on Request, reached through the custom
# bucket, and skipped on a deployment that does not have them.
CUSTOM_TIME_FIELDS = ("E_GTR_STATUS", "E_GTI_UT", "E_DELAI_PEC")


def test_status_id_is_typed_and_populated(live_client: EasyvistaClient, rich_ticket):
    assert_populated(live_client.get_ticket(rich_ticket.rfc).status_id, "STATUS_ID")


def test_urgency_and_impact_round_trip_from_create(
    live_client: EasyvistaClient, rich_ticket, live_write_config
):
    # Compared against the ids we sent, which come from secrets/ -- an id is
    # fine to assert on; a label would not be.
    ticket = live_client.get_ticket(rich_ticket.rfc)
    assert ticket.urgency_id == int(live_write_config["urgency_id"])
    assert ticket.impact_id == int(live_write_config["impact_id"])


def test_severity_is_a_declared_attribute(live_client: EasyvistaClient, rich_ticket):
    # Not set on create, so it may legitimately be None -- what this asserts is
    # that reaching it does not require digging through extra="allow" data.
    assert hasattr(live_client.get_ticket(rich_ticket.rfc), "severity_id")


def test_status_reference_resolves_to_a_display_label(
    live_client: EasyvistaClient, rich_ticket
):
    display = live_client.get_ticket(rich_ticket.rfc).reference("STATUS").display
    assert_populated(display, "STATUS reference display")


def test_official_time_fields_are_declared_and_creation_is_populated(
    live_client: EasyvistaClient, rich_ticket
):
    ticket = live_client.get_ticket(rich_ticket.rfc)
    missing = [name for name in OFFICIAL_TIME_FIELDS if not hasattr(ticket, name)]
    assert not missing, f"Request does not declare {missing}"
    assert_populated(ticket.creation_date_ut, "CREATION_DATE_UT")


@pytest.mark.parametrize("field", CUSTOM_TIME_FIELDS)
def test_gtr_fields_are_reachable_through_the_custom_bucket(
    live_client: EasyvistaClient, rich_ticket, field
):
    # Parametrized over FIXED field names, never over live values (P2). Each
    # skips independently on an instance without that field (P1).
    custom = live_client.get_ticket(rich_ticket.rfc).classify_fields().custom
    require_field(custom, field)


def test_custom_bucket_holds_only_e_prefixed_fields(
    live_client: EasyvistaClient, rich_ticket
):
    # The rule that keeps the library portable: declaring the official time
    # fields in Task 5 must not have pulled any of them into the custom bucket.
    custom = live_client.get_ticket(rich_ticket.rfc).classify_fields().custom
    assert all(key.upper().startswith("E_") for key in custom)


def test_description_round_trips_through_the_comment_memo(
    live_client: EasyvistaClient, ticket_factory
):
    # Phase 0 follow-up, verified live: `RequestUpdate.description` writes the
    # ticket's COMMENT memo, not DESCRIPTION, and a description supplied at
    # CREATE time is not readable back through either. On this deployment
    # DESCRIPTION is empty on every ticket sampled (0/15, portal-created
    # included) while COMMENT is populated on all of them -- so COMMENT is
    # where a ticket's body text lives here. This pins the path that works.
    rfc = ticket_factory()
    body = f"EVCLI{uuid.uuid4().hex[:10].upper()}BODY"
    live_client.update_ticket(rfc, RequestUpdate(description=body))
    text = live_client.resolve_memo(f"requests/{rfc}/comment")
    assert_populated(text, "COMMENT memo after update_ticket")
    assert body in html_to_text(text or ""), (
        "text written via RequestUpdate.description is not readable back from "
        "the ticket's COMMENT memo"
    )


def test_description_memo_is_addressable(live_client: EasyvistaClient, rich_ticket):
    # DESCRIPTION is a real, correctly-addressed Memo sub-resource even where it
    # is unused: the ticket record carries its HREF and the endpoint answers.
    # Whether it holds text is per-deployment, so content is skip-gated (P1)
    # rather than asserted -- this instance leaves it empty.
    raw = live_client.get_ticket(rich_ticket.rfc).description
    assert isinstance(raw, dict) and "HREF" in raw, (
        "DESCRIPTION is not an href object on the single-ticket GET"
    )
    text = live_client.resolve_memo(raw["HREF"])
    assert text is None or isinstance(text, str)
    if not (text and text.strip()):
        pytest.skip("DESCRIPTION is unused on this instance (COMMENT carries the body)")
    assert_populated(html_to_text(text), "DESCRIPTION after html_to_text")
