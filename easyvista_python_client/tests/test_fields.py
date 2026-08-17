from datetime import datetime, timedelta, timezone

from easyvista_python_client._fields import _label, _text


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


def test_label_prefers_first_non_empty_key_and_drops_href():
    obj = {"STATUS_EN": "", "STATUS_FR": "En cours", "HREF": "http://x/api/v1"}
    assert _label(obj, ("STATUS_EN", "STATUS_FR")) == "En cours"


def test_label_returns_empty_for_non_dict_or_missing_keys():
    assert _label(None, ("A",)) == ""
    assert _label({"B": "x"}, ("A",)) == ""
