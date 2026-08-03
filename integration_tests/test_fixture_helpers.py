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
