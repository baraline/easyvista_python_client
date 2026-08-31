from datetime import datetime, timedelta, timezone

from easyvista_python_client._fields import _text


def test_text_strips_strings_and_ignores_non_strings():
    assert _text("  hi  ") == "hi"
    assert _text(None) == ""
    assert _text(123) == ""


def test_text_renders_an_aware_datetime_as_the_ev_wire_format():
    value = datetime(
        2026, 8, 17, 15, 40, 41, 610000, tzinfo=timezone(timedelta(hours=2))
    )
    assert _text(value) == "2026-08-17T15:40:41.610+02:00"


def test_text_renders_a_naive_datetime_via_isoformat_fallback():
    # format_ev_datetime refuses a naive datetime; _text must never raise, so it
    # falls back to plain .isoformat() rather than propagating that ValueError.
    value = datetime(2026, 8, 17, 15, 40, 41)
    assert _text(value) == "2026-08-17T15:40:41"

