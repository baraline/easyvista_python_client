"""Tests for EasyVista's timestamp format.

The format was established live on 2026-08-17: ISO 8601 with an explicit UTC
offset and millisecond precision, e.g. ``2026-08-17T15:40:41.610+02:00``. An
unset date comes back as the empty string, not ``null``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from easyvista_python_client import format_ev_datetime, parse_ev_datetime


def test_parses_the_live_format_with_offset_and_milliseconds():
    """The exact shape measured live (9999-99-99A99:99:99.999+99:99)."""
    dt = parse_ev_datetime("2026-08-17T15:40:41.610+02:00")
    assert dt == datetime(
        2026, 8, 17, 15, 40, 41, 610000, tzinfo=timezone(timedelta(hours=2))
    )
    assert dt.utcoffset() == timedelta(hours=2)


def test_parsed_value_is_always_aware():
    """ChangedRef.updated_at requires an aware datetime; a naive one is a bug."""
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
