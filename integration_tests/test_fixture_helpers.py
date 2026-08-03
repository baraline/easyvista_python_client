"""Unit tests for ``conftest.py``'s non-fixture helpers. No credentials, no network.

Marked ``integration`` by this directory's collection hook (so CI deselects
them), but they run anywhere a plain ``pytest`` runs. Everything here is pure:
the helpers under test take a client object, so a stub is enough.
"""

from __future__ import annotations

from easyvista_python_client import (
    EasyvistaAuthError,
    EasyvistaNotFound,
)
from integration_tests.conftest import _is_per_record_gap


def test_403_is_a_per_record_gap():
    """Profile-gating on the memo endpoint is a fact about the record."""
    assert _is_per_record_gap(EasyvistaAuthError("gated", status_code=403)) is True


def test_404_is_a_per_record_gap():
    """No memo on this department is a fact about the record."""
    assert _is_per_record_gap(EasyvistaNotFound("absent", status_code=404)) is True


def test_401_is_not_a_per_record_gap():
    """An expired token is a fault, not an instance fact.

    `EasyvistaAuthError` covers 401 AND 403, so swallowing the class turns a
    mid-run credential expiry into "this instance has no Consigne data" after a
    50-department scan -- a silent misreport, and the exact defect class the
    fixture's own comment says was already fixed once for transport errors.
    """
    assert _is_per_record_gap(EasyvistaAuthError("expired", status_code=401)) is False


def test_a_missing_status_code_is_not_a_per_record_gap():
    """Absent evidence is not evidence of a gap."""
    assert _is_per_record_gap(EasyvistaAuthError("no code")) is False


# --- the retry/idempotence boundary, enforced structurally --------------------

_NON_IDEMPOTENT_METHODS = ("create_ticket", "create_action", "add_document")


def test_non_idempotent_posts_never_use_the_retrying_client():
    """These three duplicate on retry, so they must not touch ``live_client``.

    ``retry_if_exception_type`` in the transport is method-blind, so a retried
    ``create_action`` yields two actions and a retried ``add_document`` yields two
    uploads. The suite asserts exactly one of each -- and the document check
    verifies by membership rather than by delta, so a duplicate upload passes
    SILENTLY. A grep is the only guard that survives someone adding a new call
    site later.
    """
    from pathlib import Path

    here = Path(__file__).resolve().parent
    offenders = []
    for path in sorted(here.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for method in _NON_IDEMPOTENT_METHODS:
            needle = "live_client." + method + "("
            if needle in source:
                offenders.append(f"{path.name}: {needle}")

    assert not offenders, (
        "these calls duplicate on retry and must go through live_write_client "
        "instead: " + ", ".join(offenders)
    )
