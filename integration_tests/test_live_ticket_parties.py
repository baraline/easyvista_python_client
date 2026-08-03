"""Live coverage of a ticket's parties and its department's Consigne.

Skipped without credentials; never runs in CI. This module deals in names and
notes, so it is the one design principle P2 constrains hardest: it asserts ids
against ids, and everything else by shape. No name, e-mail, department label or
note text is ever compared or printed -- ``any(...)`` over identity fields
yields a boolean, and every message names a field, not a value.

Reads the shared session ticket for every party assertion and mutates nothing.
The module still needs write credentials, because the shared ticket is created
by this suite -- it skips entirely without them.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import EasyvistaAuthError, EasyvistaClient, Employee
from easyvista_python_client._html import html_to_text
from integration_tests._assertions import (
    assert_populated,
    assert_shape,
    require_field,
)

pytestmark = pytest.mark.integration

PARTY_ID_FIELDS = ("requestor_id", "recipient_id", "owner_id", "department_id")
PARTY_REFERENCES = ("REQUESTOR", "RECIPIENT", "DEPARTMENT", "LOCATION")
# Employee has no ``first_name``; these are the identity columns it declares.
IDENTITY_FIELDS = ("last_name", "e_mail", "login", "identification")


def test_party_ids_are_declared_attributes(live_client: EasyvistaClient, rich_ticket):
    ticket = live_client.get_ticket(rich_ticket.rfc)
    missing = [name for name in PARTY_ID_FIELDS if not hasattr(ticket, name)]
    assert not missing, f"Request does not declare {missing}"


def test_department_id_round_trips_from_create(
    live_client: EasyvistaClient, rich_ticket, live_write_config
):
    ticket = live_client.get_ticket(rich_ticket.rfc)
    # Bound first: an int-vs-int assert makes the rewriter print
    # `where <Request repr>.department_id`, and that repr carries the nested
    # DEPARTMENT label this module exists to keep out of the output (P2).
    department_matches = ticket.department_id == int(live_write_config["department_id"])
    assert department_matches, "DEPARTMENT_ID does not match the id sent on create"


def test_party_references_resolve_to_labels(live_client: EasyvistaClient, rich_ticket):
    ticket = live_client.get_ticket(rich_ticket.rfc)
    # A boolean map, so a failure prints which references resolved -- never what
    # they resolved TO.
    resolved = {
        name: ticket.reference(name).display is not None for name in PARTY_REFERENCES
    }
    assert resolved["DEPARTMENT"], f"no DEPARTMENT label resolved (map: {resolved})"
    assert any(resolved.values()), f"no party reference resolved (map: {resolved})"


def test_requestor_resolves_to_an_employee_record(
    live_client: EasyvistaClient, rich_ticket
):
    ticket = live_client.get_ticket(rich_ticket.rfc)
    requestor_id = require_field(ticket, "REQUESTOR_ID")
    try:
        employee = live_client.get_employee(requestor_id)
    except EasyvistaAuthError:
        # GET /employees/{id} is profile-gated and not guaranteed on another
        # deployment (P1).
        pytest.skip("GET /employees/{id} is not authorized for this profile")
    assert_shape(employee, Employee, "get_employee result")
    # Bound first: `assert str(employee.employee_id) == str(requestor_id)` makes
    # the rewriter explain the call's argument, and that reprs `employee` --
    # the record's last name, e-mail and login (P2). Both ids are printable, but
    # the object they were read off is not.
    ids_match = str(employee.employee_id) == str(requestor_id)
    assert ids_match, "get_employee returned a different employee than REQUESTOR_ID"
    carries_identity = any(
        bool(getattr(employee, field, None)) for field in IDENTITY_FIELDS
    )
    assert carries_identity, (
        f"the resolved employee record carries none of {list(IDENTITY_FIELDS)}"
    )


def test_consigne_is_readable_and_reduces_to_text(
    live_client: EasyvistaClient, consigne_department_id
):
    # The Consigne: the note held on a client/department record that surfaces on
    # that client's tickets. Asserted populated and non-empty after the HTML
    # reduction -- never by content (P2).
    note = live_client.get_department_comment(consigne_department_id)
    assert_populated(note, "COMMENT_DEPARTMENT")
    assert_populated(html_to_text(note or ""), "COMMENT_DEPARTMENT after html_to_text")


def test_consigne_is_reachable_from_a_ticket(live_client: EasyvistaClient, rich_ticket):
    # The chain a downstream integration actually walks: ticket -> DEPARTMENT_ID
    # -> that department's note. Distinct from the test above, which proves the
    # endpoint works; this one proves the ticket carries what you need to get
    # there.
    ticket = live_client.get_ticket(rich_ticket.rfc)
    department_id = require_field(ticket, "DEPARTMENT_ID")
    note = live_client.get_department_comment(department_id)
    if not (note and note.strip()):
        pytest.skip("this ticket's department has no Consigne on this instance")
    assert_populated(html_to_text(note), "COMMENT_DEPARTMENT after html_to_text")
