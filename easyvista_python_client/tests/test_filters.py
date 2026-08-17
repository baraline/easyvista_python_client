from datetime import datetime, timedelta, timezone

import pytest

from easyvista_python_client import (
    escape_ev_value,
    ev_between_filter,
    ev_contains_filter,
    ev_equals_filter,
    ev_in_filter,
    ev_since_filter,
    ev_starts_with_filter,
    is_safe_ev_value,
)

_CET = timezone(timedelta(hours=1))


def test_equals_filter_quotes_the_value():
    assert ev_equals_filter("DEPARTMENT_CODE", "ACME") == 'DEPARTMENT_CODE:"ACME"'


def test_equals_filter_quotes_ints_too():
    # EasyVista quotes numerics: DEPARTMENT_ID:"60", not DEPARTMENT_ID:60.
    assert ev_equals_filter("DEPARTMENT_ID", 60) == 'DEPARTMENT_ID:"60"'


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_returns_none_so_callers_can_compose(value):
    assert ev_equals_filter("F", value) is None


def test_in_filter_joins_same_field_with_comma():
    # ',' is OR within a single field - verified live in Task 1.
    expected = 'DEPARTMENT_CODE:"A",DEPARTMENT_CODE:"B"'
    assert ev_in_filter("DEPARTMENT_CODE", ["A", "B"]) == expected


def test_in_filter_skips_blank_values():
    assert ev_in_filter("F", ["A", "", None, "B"]) == 'F:"A",F:"B"'


def test_in_filter_returns_none_when_no_usable_values():
    assert ev_in_filter("F", []) is None
    assert ev_in_filter("F", ["", "  "]) is None


def test_escape_rejects_quote():
    with pytest.raises(ValueError, match="cannot be used in an EasyVista search"):
        escape_ev_value('22" monitor')


def test_escape_allows_comma_because_it_is_inert_inside_quotes():
    # Verified live: CODE:"A,B" matches nothing rather than combining.
    assert escape_ev_value("A,B") == "A,B"


def test_equals_filter_rejects_unsafe_value():
    with pytest.raises(ValueError):
        ev_equals_filter("DEPARTMENT_CODE", 'X"')


def test_is_safe_predicate_never_raises():
    assert is_safe_ev_value("ACME") is True
    assert is_safe_ev_value('X"') is False


def test_since_emits_the_open_ended_interval():
    """``FIELD:(a;)`` — the form measured live as a watermark lower bound."""
    got = ev_since_filter("LAST_UPDATE", "2025-11-28T16:14:41")
    assert got == "LAST_UPDATE:(2025-11-28T16:14:41;)"


def test_since_accepts_a_datetime_and_formats_the_offset_literal():
    dt = datetime(2025, 11, 28, 16, 14, 41, 133000, tzinfo=_CET)
    assert ev_since_filter("LAST_UPDATE", dt) == (
        "LAST_UPDATE:(2025-11-28T16:14:41.133+01:00;)"
    )


def test_between_emits_both_bounds():
    got = ev_between_filter("LAST_UPDATE", "2025-11-28", "2099-12-31")
    assert got == "LAST_UPDATE:(2025-11-28;2099-12-31)"


def test_blank_input_returns_none_so_callers_compose_without_conditionals():
    assert ev_since_filter("LAST_UPDATE", None) is None
    assert ev_since_filter("LAST_UPDATE", "") is None
    assert ev_between_filter("LAST_UPDATE", None, None) is None


def test_between_with_only_an_end_bound_is_open_on_the_left():
    assert ev_between_filter("LAST_UPDATE", None, "2099-12-31") == (
        "LAST_UPDATE:(;2099-12-31)"
    )


@pytest.mark.parametrize(
    "bad",
    [
        '2025-11-28";DEPARTMENT_ID:"9',  # quote breakout
        "2025-11-28;2099-12-31",  # a second bound smuggled in
        "2025-11-28)",  # closes the interval early
        "2025-11-28 or 1=1",
        "today",  # a real EV token, but not a timestamp
    ],
)
def test_interval_refuses_anything_that_is_not_a_timestamp(bad):
    """The interval value is UNQUOTED, so ';' and ')' would break out of it.

    ``ev_equals_filter`` can rely on quoting; this one cannot, so it validates
    the shape instead. Refuse rather than interpolate.
    """
    with pytest.raises(ValueError, match="timestamp"):
        ev_since_filter("LAST_UPDATE", bad)


@pytest.mark.parametrize(
    "bad",
    [
        "9999-99-99",  # no such month
        "2025-02-30",  # no such day (February)
        "2025-13-45T99:99:99",  # no such month/day/time at all
        "2025-11-28T25:61:61",  # out-of-range time components
        "٢٠٢٥-١١-٢٨",  # non-ASCII digits  # noqa: RUF001
    ],
)
def test_interval_refuses_a_well_shaped_but_impossible_timestamp(bad):
    """The regex is a shape gate only; a calendar-invalid value must still be
    refused, because a dropped condition returns the whole table rather than
    an error (this is what makes a typo'd watermark dangerous).
    """
    with pytest.raises(ValueError, match="timestamp"):
        ev_since_filter("LAST_UPDATE", bad)


@pytest.mark.parametrize(
    "literal",
    [
        "2025-11-28",
        "2025-11-28T16:14:41",
        "2025-11-28 16:14:41",
        "2025-11-28T16:14:41.133+01:00",
        "2025-11-28T16:14:41.133456Z",
    ],
)
def test_interval_accepts_every_rendering_measured_live(literal):
    """The guard's acceptance side: a regression here fails CLOSED on real
    watermarks, which no rejection test would catch."""
    assert ev_since_filter("LAST_UPDATE", literal) == f"LAST_UPDATE:({literal};)"


def test_contains_wraps_the_value_in_wildcards_with_the_tilde_operator():
    """``~`` IS a pattern operator; it needs an explicit ``*`` (measured live)."""
    assert ev_contains_filter("ASSET_TAG", "LAPTOP") == 'ASSET_TAG~"*LAPTOP*"'


def test_starts_with_anchors_on_the_left_only():
    assert ev_starts_with_filter("RFC_NUMBER", "I26081") == 'RFC_NUMBER~"I26081*"'


def test_wildcard_builders_reject_a_double_quote():
    """Same reasoning as escape_ev_value: no escape for '"' exists."""
    with pytest.raises(ValueError):
        ev_contains_filter("ASSET_TAG", 'LAP"TOP')


@pytest.mark.parametrize("bad", ["LAP*TOP", "LAP%TOP"])
def test_wildcard_builders_reject_a_wildcard_inside_the_value(bad):
    """A '*' in the middle would silently change what the caller asked for.

    ``ev_contains_filter("A*B")`` would match "A" then anything then "B" rather
    than the literal "A*B", so refuse instead of quietly widening the query.
    """
    with pytest.raises(ValueError, match="wildcard"):
        ev_contains_filter("ASSET_TAG", bad)


def test_blank_wildcard_value_returns_none_not_a_match_everything_pattern():
    """``FIELD~"**"`` would match every row — the exact silent-widening shape."""
    assert ev_contains_filter("ASSET_TAG", "") is None
    assert ev_starts_with_filter("ASSET_TAG", "   ") is None
