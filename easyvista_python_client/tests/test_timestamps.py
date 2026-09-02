"""Tests for EasyVista's timestamp format.

The format was established live on 2026-08-17: ISO 8601 with an explicit UTC
offset and millisecond precision, e.g. ``2026-08-17T15:40:41.610+02:00``. An
unset date comes back as the empty string, not ``null``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from easyvista_python_client import format_ev_datetime, parse_ev_datetime
from easyvista_python_client import timestamps as timestamps_module


def test_parses_the_live_format_with_offset_and_milliseconds():
    """The exact shape measured live (YYYY-MM-DDTHH:MM:SS.mmm+HH:MM)."""
    dt = parse_ev_datetime("2026-08-17T15:40:41.610+02:00")
    assert dt == datetime(
        2026, 8, 17, 15, 40, 41, 610000, tzinfo=timezone(timedelta(hours=2))
    )
    assert dt.utcoffset() == timedelta(hours=2)


def test_parsed_value_is_always_aware():
    """Action.updated_at requires an aware datetime; a naive one is a bug."""
    assert parse_ev_datetime("2026-08-17T15:40:41.610+02:00").tzinfo is not None


def test_the_empty_string_sentinel_is_none_not_an_error():
    """An unset EasyVista date is ``""``. Measured on every unpopulated column."""
    assert parse_ev_datetime("") is None
    assert parse_ev_datetime("   ") is None
    assert parse_ev_datetime(None) is None


def test_unparseable_input_is_none_rather_than_raising():
    assert parse_ev_datetime("not-a-date") is None
    assert parse_ev_datetime(12345) is None


def test_formats_back_to_the_literal_the_interval_grammar_accepts():
    """``LAST_UPDATE:(<this>;)`` was honoured live with exactly this rendering."""
    dt = datetime(2025, 11, 28, 16, 14, 41, 133000, tzinfo=timezone(timedelta(hours=1)))
    assert format_ev_datetime(dt) == "2025-11-28T16:14:41.133+01:00"


def test_format_round_trips_through_parse():
    literal = "2026-08-17T15:40:41.610+02:00"
    assert format_ev_datetime(parse_ev_datetime(literal)) == literal


def test_format_refuses_a_naive_datetime():
    """Refuse rather than guess a zone: a naive instant cannot name a moment."""
    with pytest.raises(ValueError, match="timezone-aware"):
        format_ev_datetime(datetime(2026, 8, 17, 15, 40, 41))


@pytest.mark.parametrize(
    "basic",
    ["20260817", "20260817T154041", "20260817T154041.610", "2026W331"],
)
def test_the_iso_basic_form_is_refused_on_every_python(basic):
    """Separator-less ISO input must return ``None`` regardless of interpreter.

    This is a portability guard, not a formatting preference. ``fromisoformat``
    accepts the ISO "basic" form from Python 3.11 and rejects it on 3.10, and
    this package supports 3.10 through 3.14 -- so before the explicit refusal
    the *same wire value* parsed to an instant on four of the five supported
    versions and raised on the fifth. CI caught it exactly that way: the 3.10
    job was green while 3.11 and 3.12 failed
    ``test_a_numeric_shaped_value_raises_instead_of_becoming_an_epoch_instant``.

    EasyVista's timestamps always carry separators, so none of these is one of
    its values on any interpreter, and accepting them would let a genuine
    format change through as a plausible-looking instant.
    """
    assert parse_ev_datetime(basic) is None


def test_the_refusal_does_not_depend_on_fromisoformat(monkeypatch):
    """The guard must short-circuit, not lean on ``fromisoformat`` raising.

    Pinned against a stdlib that accepts even more shorthand later: if the
    refusal were reached only via a ``ValueError``, a future interpreter would
    silently start parsing these again and this module's other guard would go
    quiet without any test noticing.

    Substitutes the module's whole ``datetime`` binding rather than setting an
    attribute on the real class, which is a C type and refuses one.
    """

    class _NoFromIso:
        @staticmethod
        def fromisoformat(_value):  # pragma: no cover - must never be reached
            raise AssertionError("fromisoformat consulted for an ISO-basic value")

    monkeypatch.setattr(timestamps_module, "datetime", _NoFromIso)
    assert parse_ev_datetime("20260817") is None
