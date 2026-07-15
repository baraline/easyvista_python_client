import pytest

from easyvista_python_client import (
    escape_ev_value,
    ev_equals_filter,
    ev_in_filter,
    is_safe_ev_value,
)


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
