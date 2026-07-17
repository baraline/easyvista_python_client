"""Live smoke tests against a real EasyVista instance.

Skipped automatically unless credentials are configured, via ``EASYVISTA_TEST_*``
env vars or ``secrets/easyvista_test_*`` files. Never runs in CI (which runs
``pytest -m "not integration"``). NEVER point at production.

No ticket persists from this module: it reads, plus issues a single create that
the server is *expected to reject* (``test_missing_mandatory_field_raises_
validation_error``). The ticket-creating fixture lives in ``conftest.py`` and is
used by ``test_live_search_syntax``.
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

pytestmark = pytest.mark.integration


def test_search_tickets_read_only(live_client: EasyvistaClient) -> None:
    result = live_client.search_tickets(max_rows=1)
    assert isinstance(result.total_record_count, int)
    assert result.total_record_count >= 0
    assert len(result.records) <= 1
    assert all(isinstance(r, Request) for r in result.records)


def test_get_ticket(live_client: EasyvistaClient, sample_rfc: str) -> None:
    ticket = live_client.get_ticket(sample_rfc)
    assert isinstance(ticket, Request)
    assert ticket.rfc_number == sample_rfc


def test_search_assets_read_only(live_client: EasyvistaClient) -> None:
    result = live_client.search_assets(max_rows=1)
    assert isinstance(result.total_record_count, int)
    assert result.total_record_count >= 0
    assert len(result.records) <= 1
    assert all(isinstance(a, Asset) for a in result.records)


def test_list_actions(live_client: EasyvistaClient, sample_rfc: str) -> None:
    # Lists via the top-level GET /actions?search=REQUEST.RFC_NUMBER:"{rfc}" endpoint.
    actions = live_client.list_actions(sample_rfc)
    assert isinstance(actions, list)
    assert all(isinstance(a, Action) for a in actions)


def test_list_documents(live_client: EasyvistaClient, sample_rfc: str) -> None:
    # Validates the O5 best-guess endpoint (GET requests/{rfc}/documents) live.
    documents = live_client.list_documents(sample_rfc)
    assert isinstance(documents, list)
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
    assert ei.value.status_code == 590
