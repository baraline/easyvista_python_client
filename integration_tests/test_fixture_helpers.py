"""Unit tests for ``conftest.py``'s non-fixture helpers. No credentials, no network.

Marked ``integration`` by this directory's collection hook (so CI deselects
them), but they run anywhere a plain ``pytest`` runs. Everything here is pure:
the per-record-gap and routing checks take no client at all, and the
create/close/adoption helpers take a client *object* -- so a small stub that
implements just the one or two methods each helper calls is enough; no live
credentials or network access are needed anywhere in this file.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import (
    EasyvistaAuthError,
    EasyvistaConnectionError,
    EasyvistaNotFound,
    EasyvistaValidationError,
)
from integration_tests.conftest import (
    _adopt_by_title,
    _close_tracked,
    _create_tracked,
    _InconclusiveCreate,
    _is_per_record_gap,
)


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


# --- reconciliation of a create whose outcome is unknown ----------------------


class _StubRow:
    """Enough of a ``Request`` for the reconciliation checks."""

    def __init__(self, title: str | None, rfc: str | None) -> None:
        self.title = title
        self.rfc_number = rfc


class _StubResult:
    """Enough of a ``SearchResult``. ``total`` defaults to an honoured search."""

    def __init__(self, records: list[_StubRow], total: int | None = None) -> None:
        self.records = records
        self.total_record_count = len(records) if total is None else total


class _StubSearchClient:
    """Also asserts the reconciliation search's ``fields=`` projection.

    ``_adopt_by_title`` must always request ``["RFC_NUMBER", "TITLE"]``: the
    default list projection returns TITLE present but EMPTY (measured live), so
    without this projection the byte-equal comparison against the queried title
    can never match and every reconciliation is inconclusive forever. Asserting
    it here, rather than merely accepting whatever is passed, turns a future
    accidental removal of the projection into an immediate offline failure on
    every adoption test instead of a silent revert to permanently-dead adoption
    that only a live run would ever surface.
    """

    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls = 0

    def search_tickets(self, *, search=None, max_rows=None, fields=None):
        self.calls += 1
        assert fields == ["RFC_NUMBER", "TITLE"], (
            "the reconciliation search must always project RFC_NUMBER and TITLE "
            f"explicitly (got fields={fields!r}) -- see the class docstring"
        )
        if self._error is not None:
            raise self._error
        return self._result


def test_adopt_returns_the_rfc_of_an_exact_single_match():
    client = _StubSearchClient(_StubResult([_StubRow("EVCLIABCRICH", "I1")]))
    assert _adopt_by_title(client, "EVCLIABCRICH") == "I1"


def test_adopt_returns_none_when_the_search_is_honoured_and_empty():
    """An authoritative empty is the ONLY licence to re-send the create."""
    client = _StubSearchClient(_StubResult([]))
    assert _adopt_by_title(client, "EVCLIABCRICH") is None


def test_adopt_raises_when_the_condition_was_dropped():
    """The whole-table response, which is this API's failure mode for a bad filter.

    total_record_count far exceeds the returned rows, so the TITLE condition was
    ignored. Returning None here would re-send a create that may already have
    committed; returning a row would adopt an arbitrary live ticket.
    """
    client = _StubSearchClient(
        _StubResult(
            [_StubRow("something else", "I9"), _StubRow("another", "I8")], total=3843
        )
    )
    with pytest.raises(_InconclusiveCreate):
        _adopt_by_title(client, "EVCLIABCRICH")


def test_adopt_raises_when_the_reported_total_disagrees_with_an_empty_page():
    """Isolates the honoured-search check itself, not the non-matching-row branch.

    ``test_adopt_raises_when_the_condition_was_dropped`` above supplies non-empty,
    non-matching rows, so it still raises via the "returned rows are not ours"
    branch even with the ``total_record_count != returned`` check deleted -- it
    passes for the wrong reason and has no mutation that turns it red. This one
    supplies ZERO rows with a nonzero total: the ONLY thing that can flag that
    shape is the honoured-search check. Without it, an empty ``result.records``
    falls straight through to ``return None`` -- a licensed re-send against a
    search the server never actually answered.
    """
    client = _StubSearchClient(_StubResult([], total=3843))
    with pytest.raises(_InconclusiveCreate):
        _adopt_by_title(client, "EVCLIABCRICH")


def test_adopt_never_searches_an_unquotable_title():
    """probe_tickets' second title carries a literal double quote.

    EasyVista has no escape for it and the suite asserts live that all three
    renderings match nothing, so this create is unreconcilable BY CONSTRUCTION.
    It must stop loudly rather than re-send.
    """
    client = _StubSearchClient(_StubResult([]))
    with pytest.raises(_InconclusiveCreate):
        _adopt_by_title(client, 'EVCLIABCB 22" monitor')
    assert client.calls == 0, "an unquotable title must never reach the API"


def test_adopt_raises_when_the_search_itself_fails():
    """Confirms the exception is sanitized, not merely that its str() looks clean.

    `EasyvistaConnectionError.__str__` interpolates the transport's message (P2),
    and a bare `str(info.value)` assertion cannot see a leak carried on the
    exception's ``__cause__``/``__context__`` chain rather than in its own message
    -- exactly how `raise ... from exc` leaked before this fix. ``__context__`` is
    NOT asserted to be ``None``: raising from inside an active ``except`` block
    always populates it with the exception being handled, regardless of the
    ``from`` clause (verified: even explicitly pre-clearing it does not survive the
    ``raise`` statement). ``__suppress_context__`` is the flag ``from None`` sets
    and the one pytest's chain repr actually honours -- with it True, the
    suppressed exception's text is never rendered even though the object is still
    reachable via ``.__context__`` for anyone introspecting live rather than
    reading a report (verified against real pytest ``--tb=short`` output: the
    marker text of the inner exception never appears).
    """
    client = _StubSearchClient(error=EasyvistaConnectionError("connection failed"))
    with pytest.raises(_InconclusiveCreate) as info:
        _adopt_by_title(client, "EVCLIABCRICH")

    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


def test_adopt_raises_on_a_non_matching_row():
    """Rows came back but none is ours: honoured or not, the answer is unclear."""
    client = _StubSearchClient(_StubResult([_StubRow("EVCLIOTHER", "I2")]))
    with pytest.raises(_InconclusiveCreate):
        _adopt_by_title(client, "EVCLIABCRICH")


def test_adopt_raises_when_the_matched_row_has_no_rfc():
    client = _StubSearchClient(_StubResult([_StubRow("EVCLIABCRICH", None)]))
    with pytest.raises(_InconclusiveCreate):
        _adopt_by_title(client, "EVCLIABCRICH")


def test_adopt_raises_when_two_rows_share_the_exact_title():
    """Adopting the first of two exact matches would silently orphan the other.

    ``max_rows=2`` legitimately admits this shape: two rows both titled exactly
    ``title``. Picking ``matches[0]`` and returning would register only one RFC for
    cleanup -- the same failure mode this whole helper exists to close, one row
    later.
    """
    client = _StubSearchClient(
        _StubResult([_StubRow("EVCLIABCRICH", "I1"), _StubRow("EVCLIABCRICH", "I2")])
    )
    with pytest.raises(_InconclusiveCreate):
        _adopt_by_title(client, "EVCLIABCRICH")


# --- the create helper: append-before-assert, and reconciliation on retry -----

_CFG = {
    "catalog_code": "INC_STANDARD",
    "origin": "1",
    "department_id": "2",
    "urgency_id": "3",
    "impact_id": "4",
    "status_guid": "{00000000-0000-0000-0000-000000000000}",
}


class _StubTicket:
    def __init__(self, rfc: str | None) -> None:
        self.rfc_number = rfc


class _StubWriteClient:
    """Replays a scripted list of create outcomes; an Exception item is raised."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def create_ticket(self, _post):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_create_tracked_registers_the_rfc_and_does_not_search():
    """The green path costs zero extra requests."""
    write = _StubWriteClient([_StubTicket("I1")])
    search = _StubSearchClient(_StubResult([]))
    tracked: list[str] = []

    rfc = _create_tracked(
        write, search, _CFG, tracked, title="EVCLIAAA", description="d"
    )

    assert rfc == "I1"
    assert tracked == ["I1"]
    assert search.calls == 0, "a conclusive create must not trigger reconciliation"


def test_create_tracked_adopts_a_committed_ticket_with_no_rfc_in_the_body():
    """The orphan path, closed: the ticket exists, so it must become trackable."""
    write = _StubWriteClient([_StubTicket(None)])
    search = _StubSearchClient(_StubResult([_StubRow("EVCLIAAA", "I7")]))
    tracked: list[str] = []

    rfc = _create_tracked(
        write, search, _CFG, tracked, title="EVCLIAAA", description="d"
    )

    assert rfc == "I7"
    assert tracked == ["I7"], "an adopted ticket must be registered for cleanup"
    assert write.calls == 1, "nothing committed-and-found may be re-sent"


def test_create_tracked_resends_only_after_an_authoritative_empty():
    """This is the cascade fix: a transient no longer ends the session."""
    write = _StubWriteClient(
        [EasyvistaConnectionError("connection failed"), _StubTicket("I2")]
    )
    search = _StubSearchClient(_StubResult([]))
    tracked: list[str] = []

    rfc = _create_tracked(
        write, search, _CFG, tracked, title="EVCLIAAA", description="d"
    )

    assert rfc == "I2"
    assert tracked == ["I2"]
    assert write.calls == 2, "the second attempt should have been made"


def test_create_tracked_stops_when_reconciliation_is_inconclusive():
    """Never re-send blind: one loud stop beats a duplicate nobody can see."""
    write = _StubWriteClient([EasyvistaConnectionError("connection failed")])
    search = _StubSearchClient(_StubResult([_StubRow("x", "I9")], total=3843))
    tracked: list[str] = []

    with pytest.raises(_InconclusiveCreate):
        _create_tracked(write, search, _CFG, tracked, title="EVCLIAAA", description="d")
    assert write.calls == 1
    assert tracked == []


def test_create_tracked_does_not_absorb_a_validation_error():
    """A 590 is deterministic and means a real defect -- it must propagate."""
    write = _StubWriteClient([EasyvistaValidationError("nope", status_code=590)])
    search = _StubSearchClient(_StubResult([]))

    with pytest.raises(EasyvistaValidationError):
        _create_tracked(write, search, _CFG, [], title="EVCLIAAA", description="d")
    assert write.calls == 1, "a validation error must not be retried"


def test_create_tracked_exhausts_all_attempts_then_stops():
    """Pins the spec's headline constraint: N attempts, at most one ticket, ever.

    Three transients, each followed by an honoured-and-empty reconciliation --
    every attempt is licensed to re-send, and the helper uses all three before
    giving up. Without this test, changing `_CREATE_ATTEMPTS`'s consumption (the
    `range(_CREATE_ATTEMPTS)` bound) or swapping the terminal `raise
    AssertionError` for a silent `return None` (making the `-> str` annotation a
    lie) would break nothing else here.
    """
    write = _StubWriteClient([EasyvistaConnectionError("connection failed")] * 3)
    search = _StubSearchClient(_StubResult([]))
    tracked: list[str] = []

    with pytest.raises(AssertionError):
        _create_tracked(write, search, _CFG, tracked, title="EVCLIAAA", description="d")

    assert write.calls == 3
    assert tracked == []


class _StubCloseClient:
    """Records closes; raises for any RFC in ``failing``."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.closed: list[str] = []
        self._failing = failing or set()

    def close_ticket(self, rfc, *, status_guid, delete_actions, comment):
        if rfc in self._failing:
            raise EasyvistaConnectionError("connection failed")
        self.closed.append(rfc)


def test_close_tracked_attempts_every_ticket_despite_a_failure():
    client = _StubCloseClient(failing={"I2"})

    with pytest.raises(RuntimeError) as info:
        _close_tracked(client, _CFG, ["I1", "I2", "I3"], "cleanup")

    assert client.closed == ["I1", "I3"], "one failure must not orphan the rest"
    assert "I2" in str(info.value)


def test_close_tracked_error_text_carries_no_server_prose():
    """The error records the exception TYPE, never the exception.

    ``str(exc)`` is the transport's message, which interpolates whatever the server
    said (P2). The old loops appended the exception object itself. The chain
    assertions matter as much as the message ones: pytest's chain repr renders
    ``__cause__``/``__context__`` even under ``--tb=short``, so a leak riding the
    chain rather than the message would pass a bare ``str(info.value)`` check.
    Here both are genuinely ``None`` -- not merely suppressed -- because the final
    ``raise RuntimeError(...)`` sits OUTSIDE the per-ticket ``try``/``except``, so
    no exception is "being handled" at the point it is raised (verified: unlike
    ``_adopt_by_title``'s search-failure path, there is no active exception state
    left to inherit).
    """
    client = _StubCloseClient(failing={"I1"})

    with pytest.raises(RuntimeError) as info:
        _close_tracked(client, _CFG, ["I1"], "cleanup")

    message = str(info.value)
    assert "EasyvistaConnectionError" in message
    assert "connection failed" not in message
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
