"""Live coverage of ticket attachments: upload, list, and download round-trip.

Skipped without credentials; never runs in CI. Filenames and payloads are
synthetic ``EVCLI<nonce>`` values this module authors, so every byte compared
here is one we wrote (design principle P2).

This module WRITES: each test takes a fresh ticket from ``ticket_factory``
(closed in teardown) and attaches a file to it.
"""

from __future__ import annotations

import uuid

import pytest

from easyvista_python_client import Document, EasyvistaClient
from integration_tests._assertions import assert_populated, require_field

pytestmark = pytest.mark.integration


def _nonce() -> str:
    return uuid.uuid4().hex[:10].upper()


def _upload(
    live_client: EasyvistaClient, rfc: str, suffix: str, payload: bytes
) -> Document:
    """Attach ``payload`` under a synthetic filename; return the listed record.

    Goes back through ``list_documents`` rather than trusting the upload
    response, because the two shapes differ: the POST returns an HREF-only body
    on some instances.
    """
    filename = f"evcli-{_nonce()}{suffix}"
    live_client.add_document(rfc, filename=filename, content=payload)
    documents = live_client.list_documents(rfc)
    match = next((d for d in documents if d.filename == filename), None)
    assert match is not None, (
        f"uploaded {filename} is absent from the {len(documents)}-item list for {rfc}"
    )
    return match


def test_upload_appears_in_the_document_list(
    live_client: EasyvistaClient, ticket_factory
):
    rfc = ticket_factory()
    document = _upload(live_client, rfc, ".txt", b"capability-suite probe payload\n")
    assert_populated(document.filename, "document filename")


def test_download_round_trips_text_bytes(live_client: EasyvistaClient, ticket_factory):
    rfc = ticket_factory()
    payload = f"EVCLI{_nonce()} capability-suite payload\n".encode()
    document = _upload(live_client, rfc, ".txt", payload)
    # Bound first: an inline `assert live_client.download_document(document)
    # == payload` makes the rewriter print the call's arguments, and `document`
    # is a server-returned extra="allow" record, not a value this module
    # authored (P2). The bytes are ours, but the Document is not.
    round_trips = live_client.download_document(document) == payload
    assert round_trips, "downloaded bytes differ from the uploaded payload"


def test_download_round_trips_non_utf8_bytes(
    live_client: EasyvistaClient, ticket_factory
):
    # Documents go up as base64 inside a JSON body. Every byte value plus a few
    # that are invalid UTF-8 on their own -- if anything in that path decodes
    # and re-encodes as text, this is what catches it.
    rfc = ticket_factory()
    payload = bytes(range(256)) + b"\xff\xfe\x00\x01"
    document = _upload(live_client, rfc, ".bin", payload)
    round_trips = live_client.download_document(document) == payload
    assert round_trips, "downloaded bytes differ from the uploaded binary payload"


def test_document_identifier_fields_are_present(
    live_client: EasyvistaClient, ticket_factory
):
    # DOCUMENT_ID and DDL_HREF are what Phase 0 (U2) settled; each is gated
    # separately so an instance exposing one shape and not the other skips the
    # half it lacks rather than failing (P1).
    rfc = ticket_factory()
    document = _upload(live_client, rfc, ".txt", b"identifier probe\n")
    require_field(document, "DOCUMENT_ID")
    require_field(document, "DDL_HREF")


def test_documents_reach_the_ticket_context(
    live_client: EasyvistaClient, ticket_factory
):
    rfc = ticket_factory()
    document = _upload(live_client, rfc, ".txt", b"context probe\n")
    context = live_client.get_ticket_context(rfc)
    assert any(d.filename == document.filename for d in context.documents), (
        "the uploaded attachment is missing from get_ticket_context().documents"
    )
