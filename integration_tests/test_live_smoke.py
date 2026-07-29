"""Live smoke tests against a real EasyVista instance.

Skipped automatically unless credentials are configured, via ``EASYVISTA_TEST_*``
env vars or ``secrets/easyvista_test_*`` files. Never runs in CI (which runs
``pytest -m "not integration"``). NEVER point at production.

No ticket persists from this module: it reads, plus issues a single create that
the server is *expected to reject* (``test_missing_mandatory_field_raises_
validation_error``). The ticket-creating fixture lives in ``conftest.py`` and is
used by ``test_live_search_syntax``.

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

import pytest

from easyvista_python_client import (
    Action,
    Asset,
    Document,
    EasyvistaClient,
    EasyvistaValidationError,
    PostRequest,
    Request,
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


def test_missing_mandatory_field_raises_validation_error(
    live_client: EasyvistaClient, sample_catalog_code: str
) -> None:
    # Creating with a catalog but no title is rejected by EasyVista (no ticket
    # created), so this stays read-only-safe by construction. The catalog code
    # must be *valid* on this instance: the missing title has to be the only
    # defect in the payload, or the 590 can't be attributed to it -- an unknown
    # catalog would raise 590 too, and the assertion would prove nothing.
    with pytest.raises(EasyvistaValidationError) as ei:
        live_client.create_ticket(PostRequest(catalog_code=sample_catalog_code))
    # Bound first: asserting on `ei.value.status_code` makes the rewriter render
    # the ExceptionInfo, and that prints the exception's own message -- server
    # prose this suite did not author, on a payload naming a real catalog (P2).
    status_code = ei.value.status_code
    assert status_code == 590, "creating without a title did not raise HTTP 590"
